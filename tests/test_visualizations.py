"""generate_charts() produces non-empty PNGs for the expected chart names."""

from pathlib import Path

from core.visualizations import CHART_FILENAMES, generate_charts


def test_generate_charts(seed42_db: Path, tmp_path: Path):
    out_dir = tmp_path / "charts"
    paths = generate_charts(db_path=str(seed42_db), out_dir=str(out_dir))

    assert set(paths.keys()) == set(CHART_FILENAMES.keys())

    for name, path in paths.items():
        p = Path(path)
        assert p.exists(),       f"{name}: file missing at {p}"
        assert p.suffix == ".png", f"{name}: not a .png ({p.suffix})"
        assert p.stat().st_size > 0, f"{name}: file is empty"
