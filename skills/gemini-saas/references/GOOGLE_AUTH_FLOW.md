# Google Authentication Flow for Gemini SaaS

## Overview

This document describes the Google authentication flow used by the OZ-PI Gemini SaaS Re-Authenticator skill.

## Authentication Steps

### 1. Initial Navigation
- Navigate to `https://accounts.google.com/signin`
- Wait for page to fully load

### 2. Email Entry
- Selector: `input[type="email"]` or `#identifierId`
- Enter: `ozzyclaw9085@gmail.com`
- Click: `#identifierNext`

### 3. Password Entry
- Selector: `input[type="password"]`
- Enter: (decrypted from `~/.oz_gemini.enc`)
- Click: `#passwordNext`

### 4. Challenge Handling (if required)
Possible challenges:
- **2-Step Verification**: User completes on device
- "Is this you?" prompt: User confirms
- CAPTCHA: User solves
- Security check: User reviews activity

### 5. Session Establishment
- On successful auth, Google redirects
- Session cookies are set

### 6. Gemini Navigation
- Navigate to `https://gemini.google.com/app`
- Wait for Gemini interface to load

### 7. Cookie Extraction
Extract the following cookies:
- `__Secure-1PSID` (essential)
- `__Secure-1PSIDTS` (timestamp)
- `__Secure-1PSIDCC` (cross-site)
- `SID`, `SSID`, `APISID`, `SAPISID` (Google session)

## Required Cookies

### Essential
- `__Secure-1PSID`: Primary session identifier

### Recommended
- `__Secure-1PSIDTS`: Session timestamp
- `__Secure-1PSIDCC`: Cross-site cookie consent

### Additional
- `SID`, `SSID`: Google session IDs
- `APISID`, `SAPISID`: API session IDs

## Session Lifecycle

### Creation
- Login establishes session
- Cookies set with expiration (typically 7-14 days)

### Maintenance
- Session extended with activity
- Cookies refreshed automatically

### Expiration
- Automatic after inactivity period
- Manual logout invalidates cookies

## Security Considerations

### Cookie Storage
- Encrypted at rest (`~/.oz_gemini.enc`)
- Config file: `~/.pi-mono/config.json` (600 permissions)
- Backups: `~/.pi-mono/backups/` (600 permissions)

### Browser Automation
- Headless mode supported
- Anti-detection measures:
  - Disable automation flags
  - Realistic user agent
  - Normal viewport size

### Password Security
- AES-256 encryption via Fernet
- PBKDF2 key derivation (480k iterations)
- Salt stored separately

## Error Handling

### Common Issues
1. **Invalid credentials**: Check email/password
2. **2FA required**: Complete on device
3. **CAPTCHA**: Headed mode required
4. **Session expired**: Re-run authenticator

### Recovery
- Debug screenshots saved to `debug/`
- Automatic backup before config update
- Rollback on update failure

## References

- [Google Sign-In](https://developers.google.com/identity/sign-in/web)
- [Playwright Documentation](https://playwright.dev/python/)
- [Fernet Encryption](https://cryptography.io/en/latest/fernet/)
