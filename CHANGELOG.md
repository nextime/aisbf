# AISBF Changelog

## [0.1.2] - 2026-02-06
### Changed
- Updated version from 0.1.1 to 0.1.2 for PyPI release
- Changed system installation path from /usr/local/share/aisbf to /usr/share/aisbf
- Updated aisbf.sh script to dynamically determine correct paths at runtime
- Script now checks for /usr/share/aisbf first, then falls back to ~/.local/share/aisbf
- Updated setup.py to install script with dynamic path detection
- Updated config.py to check for /usr/share/aisbf instead of /usr/local/share/aisbf
- Updated AI.PROMPT documentation to reflect new installation paths
- Script creates venv in appropriate location based on installation type
- Ensures proper main.py location is used regardless of who launches the script

## [0.1.1] - 2026-02-06
### Changed
- Updated version from 0.1.0 to 0.1.1 for PyPI release

## [0.1.0] - 2026-02-06
### Initial Release
- First public release of AISBF
- Complete AI Service Broker Framework
- Support for multiple AI providers
- Provider rotation and error tracking
- Comprehensive configuration management