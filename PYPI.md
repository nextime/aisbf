# PyPI Publishing Guide for AISBF

This guide explains how to publish the AISBF package to PyPI (Python Package Index).

## Prerequisites

1. **PyPI Account**: Create an account at https://pypi.org/account/register/
2. **Install Build Tools**:
   ```bash
   pip install build twine
   ```

3. **Configure PyPI Credentials** (optional but recommended):
   ```bash
   # Create ~/.pypirc file
   cat > ~/.pypirc << EOF
   [pypi]
   username = __token__
   password = pypi-<your-api-token>
   
   [testpypi]
   username = __token__
   password = pypi-<your-testpypi-api-token>
   EOF
   ```

   To get API tokens:
   - Go to https://pypi.org/manage/account/token/
   - Create a token for PyPI and TestPyPI

## Building the Package

From the project root directory:

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build the package
python -m build
```

This creates:
- `dist/aisbf-0.99.1.tar.gz` - Source distribution
- `dist/aisbf-0.99.1-py3-none-any.whl` - Wheel distribution

## Testing the Package

### Local Testing

```bash
# Install from the built wheel
pip install dist/aisbf-0.99.1-py3-none-any.whl

# Test the installation
aisbf status
```

### TestPyPI Testing

Before publishing to PyPI, test on TestPyPI:

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ aisbf

# Test the installation
aisbf status
```

## Publishing to PyPI

Once tested successfully:

```bash
# Upload to PyPI
python -m twine upload dist/*
```

## Version Management

Before each release:

1. **Update version** in `setup.py` and `pyproject.toml`
2. **Update CHANGELOG.md** with release notes
3. **Update README.md** if needed
4. **Commit changes** to git
5. **Tag the release**:
   ```bash
   git tag -a v0.9.0 -m "Release version 0.9.0"
   git push origin v0.9.0
   ```

## Package Structure

The package includes:

- **Python Module**: `aisbf/` directory with all Python code
- **Configuration Files**: `config/` directory with JSON configs
- **Main Application**: `main.py` - FastAPI application
- **Documentation**: `README.md`, `DOCUMENTATION.md`
- **License**: `LICENSE.txt` (GPL-3.0-or-later)
- **Requirements**: `requirements.txt`

## Custom Installation Behavior

The AISBF package includes a custom install command that:

1. **Creates a virtual environment** at:
   - User: `~/.local/aisbf-venv/`
   - System: `/usr/local/aisbf-venv/`

2. **Installs configuration files** to:
   - User: `~/.local/share/aisbf/`
   - System: `/usr/local/share/aisbf/`

3. **Installs main.py** to:
   - User: `~/.local/share/aisbf/main.py`
   - System: `/usr/local/share/aisbf/main.py`

4. **Creates the aisbf script** at:
   - User: `~/.local/bin/aisbf`
   - System: `/usr/local/bin/aisbf`

## Installation from PyPI

Users can install AISBF with:

```bash
# User installation (recommended)
pip install aisbf

# System-wide installation (requires root)
sudo pip install aisbf
```

## Post-Installation OAuth2 Setup

AISBF supports OAuth2 authentication for several providers:

### Claude (Anthropic)
- Full OAuth2 PKCE flow for Claude Code (claude.ai)
- Chrome extension for remote server deployments
- Proxy-aware: automatically detects reverse proxy deployments
- Dashboard integration for easy authentication

### Kiro (Amazon Q Developer)
- Native OAuth2 support for AWS CodeWhisperer
- Multiple authentication methods (IDE credentials, kiro-cli, direct refresh token)
- Automatic credential management

### Kilocode
- Device Authorization Grant OAuth2 flow
- Seamless integration with Kilocode services

### Codex (OpenAI)
- Device Authorization Grant OAuth2 flow (same protocol as OpenAI)
- Automatic token refresh and API key exchange
- Dashboard integration for easy authentication

**Setup Instructions:**
1. Start AISBF: `aisbf`
2. Access dashboard: `http://localhost:17765/dashboard`
3. Navigate to Providers section
4. Configure OAuth2 providers and follow authentication prompts
5. For remote deployments: Install Chrome extension from dashboard

For detailed OAuth2 setup, see README.md and DOCUMENTATION.md in the installed package.

## Troubleshooting

### Build Errors

If you encounter build errors:

```bash
# Ensure all dependencies are installed
pip install --upgrade setuptools wheel build twine

# Clean and rebuild
rm -rf dist/ build/ *.egg-info
python -m build
```

### Upload Errors

If upload fails:

```bash
# Check package contents
twine check dist/*

# Verify credentials
python -m twine upload --repository testpypi dist/* --verbose
```

### Installation Issues

If users report installation issues:

1. Check Python version (requires >= 3.8)
2. Verify all dependencies are available
3. Check system permissions for installation directories

## Security Considerations

- **API Tokens**: Never commit API tokens to version control
- **Sensitive Data**: The package doesn't include API keys or sensitive configuration
- **Dependencies**: All dependencies are listed in `requirements.txt`

## Post-Release Checklist

After publishing:

- [ ] Verify package appears on PyPI
- [ ] Test installation from PyPI
- [ ] Update documentation if needed
- [ ] Announce release to users
- [ ] Monitor for issues and feedback

## Additional Resources

- [PyPI Packaging Tutorial](https://packaging.python.org/tutorials/packaging-projects/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [PyPI Upload Guide](https://pypi.org/help/#apitoken)

## Support

For issues related to packaging or publishing:
- Check the [PyPI documentation](https://pypi.org/help/)
- Review the [packaging guide](https://packaging.python.org/)
- Open an issue at: https://git.nexlab.net/nexlab/aisbf.git/issues