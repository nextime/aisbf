# Tor Hidden Service Setup Guide for AISBF

This guide explains how to configure Tor for use with AISBF, including both ephemeral and persistent hidden services.

## Prerequisites

Install Tor and the stem Python library:

```bash
# Install Tor
sudo apt install tor          # Debian/Ubuntu
sudo dnf install tor          # Fedora
brew install tor              # macOS

# Install stem library
pip install stem
```

## Tor Configuration (torrc)

### Basic Setup (Required for All Configurations)

Edit your torrc file (usually `/etc/tor/torrc` or `~/.torrc` on macOS):

```
ControlPort 9051
HashedControlPassword 16:YOUR_HASHED_PASSWORD_HERE
```

Generate a hashed password:
```bash
tor --hash-password "your_secure_password"
```

Copy the output (starts with `16:`) and paste it after `HashedControlPassword` in torrc.

### For Ephemeral Hidden Services (Default)

No additional torrc configuration needed. AISBF will create a temporary hidden service via the control port.

**AISBF Configuration (`~/.aisbf/aisbf.json`):**
```json
{
  "tor": {
    "enabled": true,
    "control_password": "your_secure_password",
    "hidden_service_dir": "",
    "hidden_service_port": 80
  }
}
```

### For Persistent Hidden Services (Production)

Add these lines to torrc:
```
HiddenServiceDir /home/yourusername/.aisbf/tor_hidden_service
HiddenServicePort 80 127.0.0.1:17765
```

**Important:** 
- Replace `/home/yourusername` with your actual home directory path
- **Tor does NOT expand `~` in torrc** - you must use absolute paths like `/home/username`
- The port `17765` should match your AISBF server port
- The directory will be created by Tor with proper permissions

**AISBF Configuration (`~/.aisbf/aisbf.json`):**
```json
{
  "tor": {
    "enabled": true,
    "control_password": "your_secure_password",
    "hidden_service_dir": "/home/yourusername/.aisbf/tor_hidden_service",
    "hidden_service_port": 80
  }
}
```

**Note:** While AISBF config can use `~/.aisbf/tor_hidden_service`, the torrc file must use the full absolute path.

## Complete torrc Example

### For Ephemeral Hidden Service:
```
ControlPort 9051
HashedControlPassword 16:872860B76453A77D60CA2BB8C1A7042072093276A3D701AD684053EC4C
```

### For Persistent Hidden Service:
```
ControlPort 9051
HashedControlPassword 16:872860B76453A77D60CA2BB8C1A7042072093276A3D701AD684053EC4C

HiddenServiceDir /home/yourusername/.aisbf/tor_hidden_service
HiddenServicePort 80 127.0.0.1:17765
```

## Restart Tor

After editing torrc, restart Tor:

```bash
sudo systemctl restart tor  # Linux
brew services restart tor   # macOS
```

## Verify Tor is Running

```bash
# Check Tor status
sudo systemctl status tor   # Linux
brew services list          # macOS

# Test control port connection
telnet 127.0.0.1 9051
```

## Get Your Onion Address

### Ephemeral Service:
The onion address is displayed in AISBF logs when the service starts.

### Persistent Service:
```bash
cat ~/.aisbf/tor_hidden_service/hostname
```

## Troubleshooting

### Permission Denied on Cookie File
Use password authentication instead of cookie authentication (as shown above).

### Connection Refused
- Verify Tor is running: `sudo systemctl status tor`
- Check ControlPort is configured in torrc
- Test connection: `telnet 127.0.0.1 9051`

### Authentication Failed
- Verify the password in aisbf.json matches the one used to generate the hash
- Check the HashedControlPassword in torrc is correct

### Hidden Service Not Created
- Check Tor logs: `sudo journalctl -u tor -n 50`
- Verify HiddenServiceDir path is correct and accessible
- Ensure AISBF server port matches the one in HiddenServicePort

### Onion Address Not Accessible
- Verify AISBF is running: `curl http://localhost:17765`
- Check Tor Browser is configured correctly
- Wait a few minutes for the hidden service to propagate

## Security Considerations

1. **Use strong passwords** for Tor control authentication
2. **Enable API authentication** in AISBF for additional security
3. **Use persistent hidden services** for production deployments
4. **Monitor access logs** for suspicious activity
5. **Keep Tor and AISBF updated** regularly
6. **Consider firewall rules** to restrict clearnet access if only using Tor

## Additional Resources

- Tor Project Documentation: https://www.torproject.org/docs/
- Tor Hidden Service Guide: https://community.torproject.org/onion-services/
- stem Library Documentation: https://stem.torproject.org/
