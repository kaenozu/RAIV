# RAIV Backlog (100 items)

This file tracks the full backlog extracted in the previous planning step.
Status values:
- [ ] not started
- [x] completed

## A. Reliability / Error Handling
- [x] 1. Unify image load failure messages
- [x] 2. Add recovery guidance for archive extraction failures
- [x] 3. Add configurable retry count for engine execution failures
- [x] 4. Add detailed logs for temp file cleanup failures
- [x] 5. Skip broken image files and auto-move to next image
- [x] 6. Add OOM-safe behavior for huge image loads
- [x] 7. Add auto backup/restore for broken config files
- [x] 8. Strengthen pre-validation for engine exe paths
- [x] 9. Add startup self-check (deps and bundled tools)
- [x] 10. Add selectable log levels (INFO/WARN/ERROR)

## B. Performance
- [x] 11. Improve prefetch queue priority by page proximity
- [x] 12. Aggressively cancel stale jobs during fast scrolling
- [x] 13. Auto-tune CPU resample cache limits
- [x] 14. Optimize repaint timing to reduce stutter
- [x] 15. Prioritize thumbnail generation in visible area
- [x] 16. Add configurable thumbnail worker count
- [x] 17. Optimize pixmap cache behavior for rotate/flip
- [x] 18. Split profiling logs into finer stages
- [x] 19. Reduce startup time to first visible image
- [x] 20. Improve prefetch prediction during continuous paging

## C. UX / Interaction
- [x] 21. Add search filter for right-panel settings
- [x] 22. Improve duplicate-keybind conflict visualization
- [x] 23. Make compare divider handle easier to grab
- [x] 24. Add configurable zoom precision display
- [x] 25. Add direct page jump by number input
- [x] 26. Add recent folders history
- [x] 27. Add drag-and-drop acceptance visual feedback
- [x] 28. Improve fullscreen UI auto-hide behavior
- [x] 29. Persist thumbnail strip size
- [x] 30. Improve side panel pinned/auto behavior

## D. Feature Expansion
- [x] 31. Add sort modes (name/date/natural)
- [x] 32. Add TIFF support
- [x] 33. Add AVIF support
- [x] 34. Add HEIF/HEIC support
- [x] 35. Restore window position across multi-monitor setups
- [x] 36. Add bookmark feature
- [x] 37. Add favorites image list
- [x] 38. Add difference-highlight mode in compare
- [x] 39. Add two-page spread mode
- [x] 40. Add slideshow mode
- [x] 41. Add processing-aware autoplay control
- [x] 42. Add metadata panel (resolution/size/format)
- [x] 43. Add EXIF orientation option
- [x] 44. Add engine preset save/load
- [x] 45. Add model-specific recommended presets

## E. Refactoring / Architecture
- [x] 46. Split config structures by functional domain
- [x] 47. Decompose monolithic main window logic
- [x] 48. Separate rendering logic from input logic
- [x] 49. Consolidate duplicated UI text dictionary handling
- [x] 50. Add broader type hints
- [x] 51. Separate config/runtime/ui state dataclasses
- [x] 52. Normalize constant naming conventions
- [x] 53. Add domain-specific exception classes
- [x] 54. Extract logging utility module
- [x] 55. Extract archive handling module

## F. Testing
- [x] 56. Introduce unit test foundation (pytest)
- [x] 57. Add tests for config key binding helpers
- [x] 58. Add tests for key binding normalization
- [x] 59. Add tests for duplicate binding detection
- [x] 60. Add tests for image ordering logic
- [x] 61. Add tests for archive image extraction logic
- [x] 62. Add tests for temp cleanup behavior
- [x] 63. Extract UI-independent logic for testability
- [x] 64. Prepare regression sample image set
- [x] 65. Add manual E2E test checklist

## G. Documentation
- [x] 66. Add dependency management file
- [x] 67. Document development setup steps in README
- [x] 68. Document release procedure
- [x] 69. Document known constraints
- [x] 70. Expand troubleshooting section
- [x] 71. Ensure JP/EN doc parity checks
- [x] 72. Add key-config screenshots
- [x] 73. Add compare-mode GIF
- [x] 74. Add setup failure FAQ
- [x] 75. Add bundled license checklist

## H. CI/CD / Collaboration
- [x] 76. Add GitHub Actions lint/test checks (test first)
- [x] 77. Add CI startup smoke baseline (minimal)
- [x] 78. Add Windows distribution artifact workflow
- [x] 79. Add PR template
- [x] 80. Add issue templates (bug/feature)
- [x] 81. Add changelog template/process
- [x] 82. Introduce formatting policy (black/ruff)
- [x] 83. Add pre-commit hooks
- [x] 84. Add static typing checks (mypy/pyright)
- [x] 85. Add dependency vulnerability scan

## I. Operability / Diagnostics
- [x] 86. Add CLI startup options
- [x] 87. Show external engine version in UI
- [x] 88. Show command preview before execution
- [x] 89. Improve running-job progress detail
- [x] 90. Add explicit cancel button for processing
- [x] 91. Add navigation history (back/forward)
- [x] 92. Add view state snapshot save/restore
- [x] 93. Add one-click debug info copy
- [x] 94. Add minimal crash report persistence
- [x] 95. Add environment diagnostics dialog

## J. Existing-code quality tasks
- [x] 96. Further optimize path when thumbnail feature is disabled
- [x] 97. Improve interaction lock behavior during key capture
- [x] 98. Add in-app help note about Lanczos4/OpenCV fallback
- [x] 99. Audit all immediate UI refresh points after language switch
- [x] 100. Add config import/export feature

## Current milestone for this change
- [x] Add dependency files
- [x] Add pytest base config and initial tests
- [x] Add CI workflow
- [x] Add issue/PR templates
- [x] Add full backlog tracker
