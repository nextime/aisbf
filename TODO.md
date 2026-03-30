# AISBF CLI Tools Integration TODO

**Date**: 2026-03-29  
**Context**: Integration and verification of various AI CLI tools as AISBF providers  
**Goal**: Expand AISBF's provider ecosystem by supporting popular CLI tools and verifying compatibility with existing services

---

## 🔥 HIGH PRIORITY (Implement Soon)

### 1. Gemini CLI Integration
**Estimated Effort**: 2-3 days  
**Expected Benefit**: Direct access to Google's Gemini models via official CLI  
**ROI**: ⭐⭐⭐⭐ High

**Description**: Integrate Google's official Gemini CLI tool as a provider type in AISBF, allowing users to leverage their Gemini CLI credentials and configurations.

**Tasks**:
- [ ] Research Gemini CLI authentication and API structure
- [ ] Create `GeminiCLIProviderHandler` class in `aisbf/providers.py`
- [ ] Implement CLI command execution and response parsing
- [ ] Add configuration schema to `config/providers.json`
- [ ] Test with various Gemini models (Flash, Pro, Ultra)
- [ ] Add streaming support
- [ ] Update documentation with setup instructions
- [ ] Add dashboard UI support for Gemini CLI configuration

**Configuration Example**:
```json
{
  "gemini-cli": {
    "id": "gemini-cli",
    "name": "Gemini CLI",
    "type": "gemini-cli",
    "api_key_required": false,
    "gemini_cli_config": {
      "cli_path": "/usr/local/bin/gemini",
      "config_file": "~/.config/gemini/config.json"
    }
  }
}
```

---

### 2. Qwen CLI Integration
**Estimated Effort**: 2-3 days  
**Expected Benefit**: Access to Alibaba's Qwen models via CLI  
**ROI**: ⭐⭐⭐⭐ High

**Description**: Integrate Qwen CLI tool as a provider type, enabling access to Qwen's language models through their official command-line interface.

**Tasks**:
- [ ] Research Qwen CLI authentication and API structure
- [ ] Create `QwenCLIProviderHandler` class in `aisbf/providers.py`
- [ ] Implement CLI command execution and response parsing
- [ ] Add configuration schema to `config/providers.json`
- [ ] Test with available Qwen models
- [ ] Add streaming support if available
- [ ] Update documentation with setup instructions
- [ ] Add dashboard UI support for Qwen CLI configuration

**Configuration Example**:
```json
{
  "qwen-cli": {
    "id": "qwen-cli",
    "name": "Qwen CLI",
    "type": "qwen-cli",
    "api_key_required": false,
    "qwen_cli_config": {
      "cli_path": "/usr/local/bin/qwen",
      "api_key": "YOUR_QWEN_API_KEY"
    }
  }
}
```

---

### 3. GitHub Copilot CLI Integration
**Estimated Effort**: 3-4 days  
**Expected Benefit**: Leverage GitHub Copilot's code-focused models  
**ROI**: ⭐⭐⭐⭐⭐ Very High

**Description**: Integrate GitHub Copilot CLI as a provider type, allowing users to access Copilot's models through their GitHub authentication.

**Tasks**:
- [ ] Research GitHub Copilot CLI authentication flow
- [ ] Create `CopilotCLIProviderHandler` class in `aisbf/providers.py`
- [ ] Implement GitHub OAuth integration if needed
- [ ] Implement CLI command execution and response parsing
- [ ] Add configuration schema to `config/providers.json`
- [ ] Test with Copilot models
- [ ] Add streaming support
- [ ] Handle GitHub authentication tokens
- [ ] Update documentation with setup instructions
- [ ] Add dashboard UI support for Copilot CLI configuration

**Configuration Example**:
```json
{
  "copilot-cli": {
    "id": "copilot-cli",
    "name": "GitHub Copilot CLI",
    "type": "copilot-cli",
    "api_key_required": false,
    "copilot_cli_config": {
      "cli_path": "/usr/local/bin/github-copilot-cli",
      "auth_token": "ghp_xxxxxxxxxxxxx"
    }
  }
}
```

---

## 🔶 MEDIUM PRIORITY

### 4. Bolt.new Verification
**Estimated Effort**: 1-2 days  
**Expected Benefit**: Verify compatibility with Bolt.new service  
**ROI**: ⭐⭐⭐ Medium

**Description**: Verify that AISBF can work with Bolt.new (StackBlitz's AI-powered full-stack web development tool) and document any integration requirements.

**Tasks**:
- [ ] Research Bolt.new API structure and authentication
- [ ] Test existing AISBF providers with Bolt.new
- [ ] Identify any compatibility issues
- [ ] Document integration steps
- [ ] Create example configurations
- [ ] Test with various Bolt.new features
- [ ] Update documentation with Bolt.new integration guide

---

### 5. DeepSeek Verification
**Estimated Effort**: 1-2 days  
**Expected Benefit**: Verify compatibility with DeepSeek API  
**ROI**: ⭐⭐⭐ Medium

**Description**: Verify that AISBF's existing OpenAI-compatible provider handler works correctly with DeepSeek's API, or create a dedicated handler if needed.

**Tasks**:
- [ ] Research DeepSeek API structure and authentication
- [ ] Test with existing OpenAI provider handler
- [ ] Identify any API differences or incompatibilities
- [ ] Create dedicated `DeepSeekProviderHandler` if needed
- [ ] Add configuration example to `config/providers.json`
- [ ] Test with various DeepSeek models
- [ ] Document any special requirements or limitations
- [ ] Update documentation with DeepSeek integration guide

**Configuration Example**:
```json
{
  "deepseek": {
    "id": "deepseek",
    "name": "DeepSeek",
    "endpoint": "https://api.deepseek.com/v1",
    "type": "openai",
    "api_key_required": true,
    "api_key": "YOUR_DEEPSEEK_API_KEY"
  }
}
```

---

### 6. Rovo Dev CLI Verification
**Estimated Effort**: 1-2 days  
**Expected Benefit**: Verify compatibility with Atlassian Rovo Dev CLI  
**ROI**: ⭐⭐⭐ Medium

**Description**: Verify that AISBF can integrate with Atlassian's Rovo Dev CLI tool and document the integration process.

**Tasks**:
- [ ] Research Rovo Dev CLI authentication and API structure
- [ ] Test existing AISBF providers with Rovo Dev CLI
- [ ] Identify integration requirements
- [ ] Create dedicated handler if needed
- [ ] Add configuration schema
- [ ] Test with Rovo Dev features
- [ ] Document integration steps
- [ ] Update documentation with Rovo Dev CLI guide

---

## 📋 Implementation Notes

### General CLI Integration Pattern

When integrating CLI tools, follow this pattern:

1. **Authentication**: Determine how the CLI tool handles authentication (config files, environment variables, OAuth tokens)
2. **Command Execution**: Use Python's `subprocess` module to execute CLI commands
3. **Response Parsing**: Parse CLI output (JSON, plain text, etc.) into AISBF's standard format
4. **Error Handling**: Handle CLI errors, timeouts, and authentication failures
5. **Streaming**: Implement streaming if the CLI tool supports it (parse output line-by-line)
6. **Configuration**: Add CLI-specific configuration fields (cli_path, config_file, etc.)

### Testing Checklist

For each CLI tool integration:
- [ ] Test authentication flow
- [ ] Test basic chat completion
- [ ] Test streaming responses
- [ ] Test error handling
- [ ] Test with multiple models
- [ ] Test rate limiting
- [ ] Test in rotations
- [ ] Test in autoselect
- [ ] Verify dashboard configuration UI
- [ ] Update documentation

---

## 🔵 Future Enhancements

### Additional CLI Tools to Consider
- Claude CLI (official Anthropic CLI)
- Mistral CLI
- Cohere CLI
- AI21 CLI
- Perplexity CLI

### CLI Tool Management Features
- [ ] CLI tool version detection and compatibility checking
- [ ] Automatic CLI tool installation/update
- [ ] CLI tool health monitoring
- [ ] CLI tool performance benchmarking
- [ ] Unified CLI tool configuration interface

---

## 📚 Documentation Updates Required

When completing CLI tool integrations:
1. Update `README.md` with CLI tool support section
2. Update `DOCUMENTATION.md` with detailed CLI tool setup guides
3. Update `AI.PROMPT` with CLI tool configuration patterns
4. Add CLI tool examples to `API_EXAMPLES.md`
5. Update dashboard help text for CLI tool configuration
