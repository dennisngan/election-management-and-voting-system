"""Export Windows and macOS icon containers from the generated PNG artwork."""

from pathlib import Path

from PIL import Image


def main() -> None:
    assets = Path(__file__).resolve().parents[1] / "src/election/desktop/assets"
    with Image.open(assets / "election-desk.png") as source:
        if source.width != source.height or source.width < 1024:
            raise SystemExit("The icon artwork must be square and at least 1024 pixels wide")
        icon = source.convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)
    icon.save(
        assets / "election-desk.ico",
        format="ICO",
        sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)],
    )
    icon.save(assets / "election-desk.icns", format="ICNS")
    print(f"Exported election-desk.ico and election-desk.icns to {assets}")


if __name__ == "__main__":
    main()
