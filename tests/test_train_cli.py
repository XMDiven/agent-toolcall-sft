"""CLI argument handling must hand the loaders real paths."""

from pathlib import Path

from agent_toolcall_sft.training.config import load_config
from agent_toolcall_sft.training.train import build_parser, resolve_data_files


def test_defaults_come_from_the_config_as_paths():
    args = build_parser().parse_args(["--output-dir", "out"])
    train, evaluation = resolve_data_files(args, load_config("configs/qlora.yaml"))

    assert (train, evaluation) == (
        Path("data/processed/train.jsonl"),
        Path("data/processed/valid.jsonl"),
    )
    assert isinstance(train, Path) and isinstance(evaluation, Path)


def test_resume_defaults_to_off_and_accepts_a_checkpoint():
    parser = build_parser()
    assert parser.parse_args(["--output-dir", "out"]).resume_from_checkpoint is None

    args = parser.parse_args(["--output-dir", "out", "--resume-from-checkpoint", "ck/16"])
    assert args.resume_from_checkpoint == "ck/16"


def test_explicit_flags_override_and_are_still_paths():
    args = build_parser().parse_args(
        ["--output-dir", "out", "--train-file", "a.jsonl", "--eval-file", "b.jsonl"]
    )
    train, evaluation = resolve_data_files(args, load_config("configs/qlora.yaml"))

    assert (train, evaluation) == (Path("a.jsonl"), Path("b.jsonl"))
