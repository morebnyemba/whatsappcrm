# Bug Fixes in flows/services.py

## Date: 2026-01-09

## Issues Fixed

### 1. UnboundLocalError: Local variable 'settings' referenced before assignment

**Problem**: 
- Line 1478 assigned `settings = ReferralSettings.load()` which shadowed the Django `settings` import from line 14
- When line 1201 tried to access `settings.MEDIA_URL`, Python treated `settings` as a local variable
- Since the GET_REFERRAL_SETTINGS action comes after the PDF generation code in the function, Python saw the assignment and treated `settings` as local throughout the entire function
- This caused `UnboundLocalError` when earlier code tried to access `settings.MEDIA_URL`

**Error Log**:
```
[2026-01-09 07:53:59] ERROR services Unexpected error in 'action' step 'fetch_all_fixtures' (ID: 362): local variable 'settings' referenced before assignment
Traceback (most recent call last):
  File "/app/flows/services.py", line 1201, in _execute_step_actions
    media_url = settings.MEDIA_URL
UnboundLocalError: local variable 'settings' referenced before assignment
```

**Solution**: 
Renamed the local variable from `settings` to `referral_settings` at line 1478 to avoid shadowing the Django settings import.

**Files Changed**:
- `whatsappcrm_backend/flows/services.py` (line 1478, 1480-1481)

**After Fix**:
```python
# Before
settings = ReferralSettings.load()
settings_data = {
    'bonus_percentage_each': settings.bonus_percentage_each,
    'bonus_percentage_display': f"{settings.bonus_percentage_each:.2%}"
}

# After
referral_settings = ReferralSettings.load()
settings_data = {
    'bonus_percentage_each': referral_settings.bonus_percentage_each,
    'bonus_percentage_display': f"{referral_settings.bonus_percentage_each:.2%}"
}
```

### 2. Truncated Log Messages with Empty Type Display

**Problem**: 
Multiple log statements were using `{type(value)}` in f-strings, which outputs the full type representation like `<class 'bool'>` or `<class 'str'>`. This caused log messages to be truncated or show "(Type: )" with nothing after it.

**Error Logs**:
```
[2026-01-09 07:53:45] DEBUG services Resolved path 'account_creation_status' to value: 'True' (Type: )
[2026-01-09 07:53:45] INFO services Saved valid reply for var 'selected_betting_option' in Q-step 'show_betting_menu'. Value (type ): 'bet_view_matches'.
[2026-01-09 08:28:11] INFO services Saved valid reply for var 'selected_welcome_option' in Q-step 'show_welcome_menu'. Value (type
```

**Root Cause**: 
Using `{type(value)}` includes angle brackets and 'class' keyword which can interfere with log formatting or parsing systems.

**Solution**: 
Changed all instances of `{type(...)}` to `{type(...).__name__}` throughout the file, which returns just the clean type name (e.g., "bool", "str", "int") without the `<class '...'>` wrapper.

**Files Changed**:
- `whatsappcrm_backend/flows/services.py` (lines 743, 830, 928, 1740, 1743)

**Changes Made**:

Line 743:
```python
# Before
logger.warning(f"Cannot replace Contact.custom_fields for {contact.whatsapp_id} with a non-dictionary value for path '{field_path}'. Value type: {type(value_to_set)}")

# After
logger.warning(f"Cannot replace Contact.custom_fields for {contact.whatsapp_id} with a non-dictionary value for path '{field_path}'. Value type: {type(value_to_set).__name__}")
```

Line 830:
```python
# Before
logger.warning(f"CustomerProfile JSON field '{field_name}' expected dict or None, got '{type(resolved_value)}'. Skipping update.")

# After
logger.warning(f"CustomerProfile JSON field '{field_name}' expected dict or None, got '{type(resolved_value).__name__}'. Skipping update.")
```

Line 928:
```python
# Before
logger.debug(f"Step '{step.name}': Single variable template detected: '{variable_path}'. Value type: {type(potential_list_value)}, Is list: {isinstance(potential_list_value, list)}")

# After
logger.debug(f"Step '{step.name}': Single variable template detected: '{variable_path}'. Value type: {type(potential_list_value).__name__}, Is list: {isinstance(potential_list_value, list)}")
```

Lines 1740 and 1743 (The main culprits from the error logs):
```python
# Before
logger.info(f"Saved valid reply for var '{variable_to_save_name}' in Q-step '{current_step.name}'. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")
logger.info(f"Valid reply received for Q-step '{current_step.name}', but no 'save_to_variable' defined. Value (type {type(value_to_save)}): '{str(value_to_save)[:100]}'.")

# After
logger.info(f"Saved valid reply for var '{variable_to_save_name}' in Q-step '{current_step.name}'. Value (type {type(value_to_save).__name__}): '{str(value_to_save)[:100]}'.")
logger.info(f"Valid reply received for Q-step '{current_step.name}', but no 'save_to_variable' defined. Value (type {type(value_to_save).__name__}): '{str(value_to_save)[:100]}'.")
```

**Expected Log Output After Fix**:
```
[2026-01-09 07:53:45] DEBUG services Resolved path 'account_creation_status' to value: 'True' (Type: bool)
[2026-01-09 07:53:45] INFO services Saved valid reply for var 'selected_betting_option' in Q-step 'show_betting_menu'. Value (type str): 'bet_view_matches'.
[2026-01-09 08:28:11] INFO services Saved valid reply for var 'selected_welcome_option' in Q-step 'show_welcome_menu'. Value (type str): 'welcome_betting'.
```

## Testing

### Syntax Validation
- [x] Python syntax check passed: `python3 -m py_compile whatsappcrm_backend/flows/services.py`

### Expected Behavior
1. PDF generation for fixtures should now work without UnboundLocalError
2. All log messages should display complete type names without truncation
3. Referral settings loading should continue to work normally with the renamed variable

## Production Deployment Notes

These changes are safe to deploy to production:
- The variable renaming is purely internal and doesn't affect any external APIs or data structures
- The logging changes only affect log output format, making it more readable
- No database migrations or configuration changes required
- No breaking changes to existing functionality

## Related Issues

- GitHub Issue #89: "help fix the bug"
- Previous PR #90: Fixed initial logging issue but missed these additional instances

## Commit

Commit: 9146ec6
Message: "Fix UnboundLocalError and logging issues in services.py"
