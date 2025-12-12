# Webhook Signature Verification Fix

## Problem
WhatsApp webhook requests were failing with signature verification errors:
```
WARNING views Webhook signature mismatch. Expected: ..., Calculated: ...
ERROR views Webhook signature verification FAILED. Discarding request.
```

## Root Cause
The signature verification failures can be caused by several issues:

1. **Incorrect App Secret**: Using the wrong secret from Meta
2. **Whitespace in App Secret**: Leading/trailing whitespaces in the environment variable
3. **Duplicate Logging**: Logger propagation causing messages to appear twice
4. **Request Body Modification**: Proxy or middleware modifying the request

## Solution

### Changes Made

1. **Fixed Duplicate Logging** (`settings.py`)
   - Changed `'meta_integration': {'propagate': True}` to `{'propagate': False}`
   - This prevents log messages from being duplicated in the console

2. **Added Whitespace Stripping** (`views.py`)
   - App secret is now stripped of leading/trailing whitespace
   - Prevents common configuration errors

3. **Enhanced Debug Logging** (`views.py`)
   - Added detailed logging for signature verification failures
   - Logs request body size and app secret length (first 4 chars only)
   - Logs all headers for debugging

4. **Improved Documentation** (`views.py`)
   - Added comprehensive docstring explaining the correct app secret to use
   - Clarifies it should be the "App Secret" from Meta App Dashboard, not the Access Token

5. **Created Tests** (`tests.py`)
   - Comprehensive test suite for signature verification
   - Tests various edge cases and failure modes

## How to Fix Your Setup

### Step 1: Verify Your App Secret

The App Secret must be obtained from your Meta App Dashboard:

1. Go to [Meta App Dashboard](https://developers.facebook.com/apps/)
2. Select your app
3. Go to **Settings > Basic**
4. Copy the **App Secret** (you may need to click "Show")
5. **Important**: Do NOT use the WhatsApp Business API Access Token

### Step 2: Add App Secret to MetaAppConfig

**As of the latest update, the app secret is now stored in the database** (like in Kali-Safaris reference repo), not in environment variables.

1. Log into Django Admin
2. Go to **Meta Integration > Meta App Configurations**
3. Edit your active configuration
4. Add the **App Secret** in the `app_secret` field
5. Save the configuration

**Note**: The old method of using `WHATSAPP_APP_SECRET` in `.env` is deprecated. Each MetaAppConfig can now have its own app secret, allowing support for multiple WhatsApp Business accounts with different app secrets.

### Step 3: Restart Your Services

After updating the configuration:

```bash
docker-compose restart backend
# or if not using Docker:
systemctl restart your-django-service
```

### Step 4: Test the Webhook

You can test the signature verification using the standalone test script:

```bash
python3 test_signature_verification.py
```

All tests should pass, confirming the verification logic is working correctly.

### Step 5: Monitor Logs

After restarting, monitor your logs when Meta sends a webhook:

```bash
docker-compose logs -f backend
```

You should now see:
- ✅ `Webhook signature verified successfully.` (DEBUG level)
- ✅ No more "signature mismatch" warnings
- ✅ No duplicate log messages

## Debugging Tips

If you still see verification failures:

1. **Check the debug logs** - They now show:
   - Request body size
   - App secret length
   - First 4 characters of the app secret
   - All headers received

2. **Verify the webhook URL** - Make sure Meta is sending to the correct endpoint

3. **Check for proxies** - If using nginx or another proxy:
   - Ensure `proxy_buffering` is off or properly configured
   - Verify the request body isn't being modified

4. **Test with a simple curl command**:
   ```bash
   # Generate a test signature
   echo -n '{"test":"data"}' | openssl dgst -sha256 -hmac "your_app_secret" | sed 's/^.* //'
   
   # Send test request
   curl -X POST https://your-domain.com/webhook/ \
     -H "Content-Type: application/json" \
     -H "X-Hub-Signature-256: sha256=<generated_hash>" \
     -d '{"test":"data"}'
   ```

## Additional Notes

- The fix maintains backward compatibility
- No changes to the verification algorithm (it was correct)
- Enhanced logging helps diagnose configuration issues
- Tests ensure the verification logic continues to work correctly

## Meta Documentation References

- [WhatsApp Cloud API Webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components)
- [Webhook Security](https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests)
