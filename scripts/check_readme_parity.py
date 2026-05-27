from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"

REQUIRED_PAIRS = [
    ("## 初回セットアップ", "## First Setup"),
    ("## 開発者向けセットアップ", "## Developer Setup"),
    ("## 既知の制約", "## Known Constraints"),
    ("## トラブルシュート", "## Troubleshooting"),
    ("## リリース手順", "## Release Procedure"),
    ("## 起動", "## Launch"),
]


def main() -> int:
    text = README.read_text(encoding="utf-8")
    missing: list[str] = []
    for ja, en in REQUIRED_PAIRS:
        if ja not in text:
            missing.append(f"missing Japanese section: {ja}")
        if en not in text:
            missing.append(f"missing English section: {en}")
    if missing:
        print("README parity check failed:")
        for item in missing:
            print(f"- {item}")
        return 1
    print("README parity check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
