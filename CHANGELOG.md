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

### Added
- Comprehensive logging module with rotating file handlers
- Log files stored in /var/log/aisbf when launched by root
- Log files stored in ~/.local/var/log/aisbf when launched by user
- Automatic log directory creation if it doesn't exist
- Rotating file handlers with 50MB max file size and 5 backup files
- Separate log files for general logs (aisbf.log) and error logs (aisbf_error.log)
- stdout and stderr output duplicated to rotating log files
- Console logging for immediate feedback
- Logging configuration in main.py with proper setup function
- Updated aisbf.sh script to redirect output to log files
- Updated setup.py to include logging configuration in installed script

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