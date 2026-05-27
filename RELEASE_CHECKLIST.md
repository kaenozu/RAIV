# Release Checklist

## Pre-release
- [ ] Ensure `pytest` passes locally
- [ ] Confirm app launches via `run_raiv.bat`
- [ ] Verify image/folder/archive open flows
- [ ] Verify engine switching (Real-CUGAN / Real-ESRGAN)
- [ ] Verify compare mode and key bindings
- [ ] Confirm bundled tool licenses are included

## Packaging
- [ ] Include `tools/realcugan-ncnn-vulkan` binaries/models/readme/license
- [ ] Include `tools/realesrgan-ncnn-vulkan` binaries/models/readme/license
- [ ] Include `assets` icons
- [ ] Include `README.md` and `LICENSE`

## Post-release
- [ ] Tag release in Git
- [ ] Update `CHANGELOG.md`
- [ ] Publish release notes
