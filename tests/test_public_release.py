from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TRACKED_TEXT_SUFFIXES = {
    ".bicep",
    ".bicepparam",
    ".css",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_PUBLIC_MARKERS = (
    "@" + "microsoft.com",
    "c:" + "\\users\\",
    "session" + "-state",
    ".azurecontainerapps" + ".io",
    ".datawarehouse.fabric" + ".microsoft.com",
    "onedrive - " + "microsoft",
    "pkgs.visualstudio" + ".com",
    "workiqmcp2" + "testt",
    "workiqteam" + "s2",
    "e058" + "15",
    "mngenv" + "254931",
)


def tracked_files() -> list[Path]:
    import subprocess

    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def test_public_tree_excludes_generated_environment_evidence() -> None:
    tracked = [path.relative_to(ROOT).as_posix() for path in tracked_files()]

    assert not any(path.startswith(".foundry/results/") for path in tracked)
    assert not any(path.startswith("v2/agents/.foundry/results/") for path in tracked)
    assert not any(path.startswith("docs/deployment-report-") for path in tracked)
    assert not any(
        path.startswith("app/evaluation-summary.")
        and path != "app/evaluation-summary.json"
        for path in tracked
    )


def test_public_text_has_no_private_environment_markers() -> None:
    for path in tracked_files():
        if path.suffix.lower() not in TRACKED_TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8").casefold()
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            assert marker not in text, f"{marker!r} found in {path.relative_to(ROOT)}"


def test_synthetic_workbook_has_no_personal_metadata() -> None:
    workbook = ROOT / "data" / "v1" / "code_interpreter" / "SiC_AUTO_Shipments.xlsx"
    with ZipFile(workbook) as archive:
        metadata = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.endswith((".xml", ".rels"))
        ).lower()

    assert b"c:" + b"\\users\\" not in metadata
    assert b"session" + b"-state" not in metadata
    assert b"onedrive - " + b"microsoft" not in metadata
