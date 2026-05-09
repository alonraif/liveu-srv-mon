# Fix for ERR_CONTENT_LENGTH_MISMATCH and TypeError

## Problem Summary

The application was experiencing two related errors:

1. **`net::ERR_CONTENT_LENGTH_MISMATCH`** - The server was returning responses where the Content-Length header didn't match the actual content length, causing the browser to reject the response.

2. **`TypeError: Cannot read properties of undefined (reading 'map')`** - The frontend was crashing when trying to call `.map()` on `undefined` data from the failed API response.

## Root Cause Analysis

The issue occurred in this sequence:

1. The API call to `/api/status/history?range=7d` would fail with `ERR_CONTENT_LENGTH_MISMATCH`
2. The frontend's `apiFetch` function (in `api.ts`) was silently catching JSON parse errors and returning an empty object `{}`
3. This empty object was assigned to the `history` state variable
4. The `chartData` useMemo hook checked `if (!history)` but `history` was truthy (it was an object, just empty)
5. When accessing `history.samples.map(...)`, it threw because `history.samples` was `undefined`

## Changes Made

### 1. Frontend - App.tsx (Line 259)

**Before:**
```typescript
const chartData = useMemo(() => {
  if (!history) return [];
  return history.samples
    .map((s) => { ... })
}, [history]);
```

**After:**
```typescript
const chartData = useMemo(() => {
  if (!history || !history.samples) return [];
  return history.samples
    .map((s) => { ... })
}, [history]);
```

This adds null safety to prevent the crash when `history.samples` is undefined.

### 2. Frontend - api.ts (Lines 29-34)

**Before:**
```typescript
const data = await res.json().catch(() => ({}));
if (!res.ok) {
  const message = data?.detail || `Request failed (${res.status})`;
  throw new Error(message);
}
return data as T;
```

**After:**
```typescript
if (!res.ok) {
  let message = `Request failed (${res.status})`;
  try {
    const data = await res.json();
    if (data?.detail) message = data.detail;
  } catch {
    // If response body can't be parsed, check for content length mismatch
    if (res.status === 0 || res.headers.get('content-length') === null) {
      message = `Server connection error: ${res.url}`;
    }
  }
  throw new Error(message);
}
const data = await res.json();
return data as T;
```

This improves error handling by:
- Properly throwing errors for failed responses instead of silently returning empty objects
- Providing more descriptive error messages for connection issues
- Only parsing JSON for successful responses

### 3. Backend - routers/status.py (Lines 1-12, 33-48)

**Added:**
- Import for `logging`, `HTTPException`, and `status`
- Logger instance for the module
- Try-catch block around the history endpoint with proper error logging

**Changes:**
```python
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ... other imports

logger = logging.getLogger('liveu-monitor')

@router.get('/history', response_model=StatusHistoryResponse)
def status_history(...):
    try:
        days = 7
        if range_value.endswith('d') and range_value[:-1].isdigit():
            days = max(1, min(30, int(range_value[:-1])))
        samples = get_history(db, days=days)
        return StatusHistoryResponse(samples=samples)
    except Exception as e:
        logger.error(f"Error fetching status history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch status history"
        )
```

This ensures:
- Errors are properly logged with full stack traces
- The endpoint returns a proper HTTP 500 error instead of a truncated response
- The frontend receives a clear error message

## Testing Recommendations

1. **Test the history endpoint directly:**
   ```bash
   curl -k https://your-server:8443/api/status/history?range=7d
   ```

2. **Check backend logs** for any errors when the endpoint is called

3. **Monitor the frontend** to ensure the error handling works correctly when the API fails

4. **Verify the graphs** still work when data is available

## Additional Notes

The `ERR_CONTENT_LENGTH_MISMATCH` error typically indicates:
- The server crashed or encountered an error while generating the response
- The response was too large and got truncated
- There's a network/proxy issue
- The database query took too long or failed

If the error persists after these fixes, investigate:
- Database performance and connection issues
- Memory limits on the server
- Proxy or load balancer configurations
- Network stability between client and server