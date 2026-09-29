#!/usr/bin/env python
"""Run one WorldMemArena GUI question through the local Codex CLI.

This is a direct Codex subtask runner, separate from the benchmark's
Harness-Codex aggregate path.  Codex reads its provider/model/auth settings
from CODEX_HOME (the default is ~/.codex), and receives the trajectory's
candidate screenshots as --image arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Make direct ``python scripts/run_codex_gui_subtask.py`` invocation behave
# like ``python -m`` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_framework.datasets.worldmemarena import load_worldmemarena


def _images_for_sessions(sample, session_ids: set[str]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for session in sample.sessions:
        if session.session_id not in session_ids:
            continue
        for turn in session.turns:
            for attachment in turn.attachments:
                if not attachment.image_id or not attachment.file_path:
                    continue
                if attachment.image_id in seen:
                    continue
                path = Path(attachment.file_path).expanduser().resolve()
                if path.is_file():
                    seen.add(attachment.image_id)
                    out.append((attachment.image_id, str(path), session.session_id))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=".cache/worldmemarena_gui")
    parser.add_argument("--sample-index", type=int, default=1,
                        help="1-based sample index in the loaded dataset")
    parser.add_argument("--checkpoint-index", type=int, default=1,
                        help="1-based checkpoint index within the sample")
    parser.add_argument("--question-index", type=int, default=1,
                        help="1-based question index within the checkpoint")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--max-images", type=int, default=12)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", "~/.codex"))
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--output-dir", default="exp_log/codex_gui_subtask")
    args = parser.parse_args()

    codex = shutil.which(args.codex_bin) if "/" not in args.codex_bin else args.codex_bin
    if not codex:
        raise SystemExit(f"Codex CLI not found: {args.codex_bin}")

    bundle = load_worldmemarena(Path(args.dataset).expanduser())
    if not 1 <= args.sample_index <= len(bundle.samples):
        raise SystemExit(f"--sample-index must be in 1..{len(bundle.samples)}")
    sample = bundle.samples[args.sample_index - 1]
    if not 1 <= args.checkpoint_index <= len(sample.normalized_checkpoints):
        raise SystemExit(
            f"--checkpoint-index must be in 1..{len(sample.normalized_checkpoints)}"
        )
    checkpoint = sample.normalized_checkpoints[args.checkpoint_index - 1]
    if not 1 <= args.question_index <= len(checkpoint.questions):
        raise SystemExit(f"--question-index must be in 1..{len(checkpoint.questions)}")
    question = checkpoint.questions[args.question_index - 1]

    images = _images_for_sessions(sample, set(checkpoint.covered_sessions))
    images = images[: max(0, args.max_images)]
    if not images:
        raise SystemExit("No local screenshots found for this checkpoint.")

    image_index = "\n".join(
        f"- {image_id} (session {session_id})"
        for image_id, _path, session_id in images
    )
    prompt = (
        "You are solving one GUI trajectory subtask from the WorldMemArena "
        "benchmark. Inspect the attached candidate screenshots and answer the "
        "question using only those screenshots and the labels below.\n\n"
        f"Sample: {sample.sample_id}\n"
        f"Checkpoint: {checkpoint.checkpoint_id}\n"
        f"Question type: {question.question_type_abbrev}\n"
        f"Question: {question.question}\n\n"
        "Candidate screenshot labels (the labels correspond to the attached "
        "images, in the same order):\n"
        f"{image_index}\n\n"
        "Give the answer directly. Include the screenshot image id when the "
        "question asks you to identify one. Do not use shell or web tools."
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "sample_id": sample.sample_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "question_index": args.question_index,
        "question_type": question.question_type_abbrev,
        "question": question.question,
        "gold_answer": question.gold_answer,
        "images": [
            {"image_id": image_id, "path": path, "session_id": session_id}
            for image_id, path, session_id in images
        ],
        "model": args.model,
        "codex_home": str(Path(args.codex_home).expanduser()),
        "prompt": prompt,
    }
    (output_dir / "subtask.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with tempfile.NamedTemporaryFile(
        prefix="worldmemarena-codex-", suffix=".txt", dir=output_dir, delete=False
    ) as fh:
        output_path = Path(fh.name)

    cmd = [
        codex,
        "exec",
        "--model",
        args.model,
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
    ]
    # Codex treats --image's value list greedily, so the prompt must precede
    # image flags or it will try to read the prompt from stdin.
    cmd.append(prompt)
    for _image_id, path, _session_id in images:
        cmd.extend(["--image", path])

    env = dict(os.environ)
    env["CODEX_HOME"] = str(Path(args.codex_home).expanduser().resolve())
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            env=env,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
        answer = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not answer:
            answer = completed.stdout.strip()
        (output_dir / "answer.txt").write_text(answer + "\n", encoding="utf-8")
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise SystemExit(f"Codex exited with {completed.returncode}: {detail}")
        print(answer)
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
