# Release Checklist

## Pre-release
- [x] Ensure `pytest` passes locally
- [x] Confirm app launches via `RAIV.exe`
- [x] Verify image/folder/archive open flows
- [ ] Verify engine switching (Real-CUGAN / Real-ESRGAN)
- [ ] Verify compare mode and key bindings
- [x] Confirm bundled tool licenses are included

## Packaging
- [x] Include `tools/realcugan-ncnn-vulkan` binaries/models/readme/license
- [x] Include `tools/realesrgan-ncnn-vulkan` binaries/models/readme/license
- [x] Include `assets` icons
- [x] Include `README.md` and `LICENSE`

## Post-release
- [x] Tag release in Git
- [x] Update `CHANGELOG.md`
- [x] Publish release notes
