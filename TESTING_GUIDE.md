# Phase 2 Testing Guide

## Quick Start Testing

### Step 1: Install Dependencies

```powershell
cd backend
pip install SQLAlchemy==2.0.36 alembic==1.14.0 slowapi==0.1.9
```

### Step 2: Start Server

```powershell
python server.py
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
Database initialized: sqlite:///c:/Users/.../backend/audits.db
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**✅ Success Indicator:** You should see `audits.db` file created in `backend/` folder

---

## Test Suite

### Test 1: Database Persistence

**Objective:** Verify audits survive server restart

```powershell
# Start an audit
curl -X POST http://localhost:8000/api/audit/start -H "Content-Type: application/json" -d "{\"college_name\": \"Test College\"}"

# Note the audit_id in response
# Example: {"audit_id": "abc-123", ...}

# Stop server (Ctrl+C)

# Restart server
python server.py

# Check audit still exists
curl http://localhost:8000/api/audit/abc-123
```

**Expected:** ✅ Audit data retrieved successfully (not 404)

---

### Test 2: Rate Limiting

**Objective:** Verify endpoints enforce rate limits

```powershell
# Test /audit/start (limit: 10/minute)
# Run this PowerShell loop:
for ($i=1; $i -le 12; $i++) {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/audit/start" `
        -Method POST `
        -ContentType "application/json" `
        -Body '{"college_name":"Test College"}' `
        -UseBasicParsing
    Write-Host "Request $i: $($response.StatusCode)"
}
```

**Expected:**
- Requests 1-10: ✅ `200 OK`
- Request 11+: ❌ `429 Too Many Requests`

**Response Headers:**
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1707480060
```

---

### Test 3: Batch Processing

**Objective:** Start multiple audits simultaneously

```powershell
# Start batch audit
$body = @{
    college_names = @(
        "IIT Delhi",
        "IIT Bombay",
        "BITS Pilani"
    )
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/api/audit/batch" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body `
    -UseBasicParsing
```

**Expected Response:**
```json
{
  "batch_id": "uuid-here",
  "audits": [
    {
      "audit_id": "uuid-1",
      "college_name": "IIT Delhi",
      "status": "processing"
    },
    // ... 2 more
  ],
  "total": 3,
  "message": "Started 3 audits"
}
```

**Verify:**
```powershell
# Check each audit status
curl http://localhost:8000/api/audit/{audit_id_1}
curl http://localhost:8000/api/audit/{audit_id_2}
curl http://localhost:8000/api/audit/{audit_id_3}
```

---

### Test 4: Audit History

**Objective:** Retrieve historical audits for a college

**Prerequisite:** Complete at least 2 audits for the same college

```powershell
# Start multiple audits for same college over time
curl -X POST http://localhost:8000/api/audit/start `
    -H "Content-Type: application/json" `
    -d '{"college_name":"IIT Delhi"}'

# Wait for completion...

# Start another audit
curl -X POST http://localhost:8000/api/audit/start `
    -H "Content-Type: application/json" `
    -d '{"college_name":"IIT Delhi"}'

# Wait for completion...

# Get audit history
curl "http://localhost:8000/api/college/IIT%20Delhi/history?limit=5"
```

**Expected Response:**
```json
{
  "college_name": "IIT Delhi",
  "audits": [
    {
      "id": "uuid-2",
      "created_at": "2026-02-09T15:30:00",
      "status": "completed",
      "summary": {...}
    },
    {
      "id": "uuid-1",
      "created_at": "2026-02-09T14:00:00",
      "status": "completed",
      "summary": {...}
    }
  ],
  "count": 2
}
```

---

### Test 5: Audit Comparison

**Objective:** Compare two audits and see what changed

**Prerequisite:** Have two completed audits

```powershell
# Get two audit IDs from history
$audit1 = "uuid-1"
$audit2 = "uuid-2"

# Compare them
curl "http://localhost:8000/api/compare/$audit1/$audit2"
```

**Expected Response:**
```json
{
  "audit_1": {
    "id": "uuid-1",
    "date": "2026-02-09T14:00:00",
    "summary": {
      "data_found": 65,
      "high_confidence": 45
    }
  },
  "audit_2": {
    "id": "uuid-2",
    "date": "2026-02-09T15:30:00",
    "summary": {
      "data_found": 68,
      "high_confidence": 50
    }
  },
  "changes": [
    {
      "kpi": "Placement Rate",
      "change_type": "modified",
      "old_value": "85%",
      "new_value": "90%",
      "old_confidence": "high",
      "new_confidence": "high"
    }
  ]
}
```

**Change Types:**
- `added`: KPI exists in audit2 but not audit1
- `removed`: KPI exists in audit1 but not audit2  
- `modified`: KPI value changed

---

### Test 6: Latest Audit

**Objective:** Get most recent completed audit for a college

```powershell
curl "http://localhost:8000/api/college/IIT%20Delhi/latest"
```

**Expected:** ✅ Returns most recent completed audit with full results

---

### Test 7: Statistics

**Objective:** View platform-wide statistics

```powershell
curl http://localhost:8000/api/stats/overview
```

**Expected Response:**
```json
{
  "total_audits": 15,
  "completed": 12,
  "processing": 2,
  "failed": 1,
  "average_time_seconds": 145.2,
  "database": "Connected"
}
```

---

### Test 8: Data Cleanup

**Objective:** Delete old audits

```powershell
# Delete audits older than 30 days (keeps completed by default)
curl -X POST "http://localhost:8000/api/maintenance/cleanup?days=30"
```

**Expected Response:**
```json
{
  "message": "Cleanup completed",
  "deleted_audits": 5,
  "kept_completed": true
}
```

**Note:** Only failed/cancelled audits older than 30 days are deleted. Completed audits are preserved.

---

## Database Inspection

### View Database Contents

```powershell
# Install sqlite3 (if not already installed)
# Option 1: Use DB Browser for SQLite (GUI)
# Download: https://sqlitebrowser.org/

# Option 2: Use SQLite command line
sqlite3 backend/audits.db
```

**SQL Queries:**
```sql
-- View all audits
SELECT id, college_name, status, created_at FROM audits;

-- Count audits by status
SELECT status, COUNT(*) FROM audits GROUP BY status;

-- View audit results for a specific audit
SELECT kpi_name, value, system_confidence 
FROM audit_results 
WHERE audit_id = 'your-audit-id';

-- View recent rate limit entries
SELECT identifier, endpoint, timestamp 
FROM rate_limits 
ORDER BY timestamp DESC 
LIMIT 10;

-- Check database file size
.databases

-- Exit
.exit
```

---

## Frontend Integration Testing

### Update Frontend Connection

**In `frontend/src/App.js`:**

```javascript
// All endpoints should work with database backend
// No changes needed to frontend code!

// Test existing features:
// 1. Start audit → should persist in database
// 2. Check status → should query from database
// 3. View results → should show from database
```

### Start Frontend

```powershell
cd frontend
npm start
```

**Test Flow:**
1. Start an audit via UI
2. Stop backend server
3. Restart backend server
4. Refresh frontend
5. ✅ Audit should still be visible (persisted!)

---

## Load Testing

### Test Rate Limiting Under Load

```powershell
# Install Apache Bench (optional)
# or use PowerShell script

# Blast 100 requests in parallel
$jobs = 1..100 | ForEach-Object {
    Start-Job -ScriptBlock {
        Invoke-WebRequest -Uri "http://localhost:8000/api/audit/start" `
            -Method POST `
            -ContentType "application/json" `
            -Body '{"college_name":"Load Test"}' `
            -UseBasicParsing
    }
}

# Wait for all jobs
$jobs | Wait-Job

# Check results
$jobs | Receive-Job | Select-Object StatusCode | Group-Object StatusCode
```

**Expected:**
- Some `200 OK` (within rate limit)
- Many `429 Too Many Requests` (rate limited)

---

## Troubleshooting

### Issue: Database Not Created

**Symptom:** No `audits.db` file in backend folder

**Solution:**
```powershell
# Check server output for errors
python server.py

# Manually test database
cd backend
python -c "from database import init_database; db = init_database(); print('OK')"
```

### Issue: Import Error for SQLAlchemy

**Symptom:** `ModuleNotFoundError: No module named 'sqlalchemy'`

**Solution:**
```powershell
cd backend
pip install -r requirements.txt
```

### Issue: Rate Limit Not Working

**Symptom:** Can make unlimited requests

**Solution:**
1. Check server logs for `limiter` initialization
2. Verify slowapi is installed: `pip show slowapi`
3. Check if running behind reverse proxy (need to configure `X-Forwarded-For`)

### Issue: Audit History Empty

**Symptom:** `/college/{name}/history` returns no results

**Possible Causes:**
1. College name doesn't match exactly (e.g., "IIT Delhi" vs "iit delhi")
2. No completed audits yet
3. Different college name format

**Solutions:**
```powershell
# List all audits to see actual names
curl http://localhost:8000/api/audits

# Use exact college_name from list
curl "http://localhost:8000/api/college/IIT%20Delhi/history"
```

### Issue: Comparison Shows No Changes

**Symptom:** `/compare/{id1}/{id2}` returns empty `changes` array

**This is normal if:**
- Both audits extracted same KPIs with same values
- Audits are for different colleges (shouldn't compare)

**To test comparison:**
1. Run audit for a college
2. Manually update KPI in database
3. Run audit again
4. Compare → should show modifications

---

## Performance Benchmarks

### Expected Performance

**Single Audit:**
- Database write: < 10ms
- Database read: < 5ms
- Full audit (with KPI extraction): 120-180 seconds

**Batch Audit (3 colleges):**
- Database writes: < 30ms
- Full completion: 360-540 seconds (parallel processing)

**History Query:**
- < 20ms for 100 audits
- < 50ms for 10,000 audits

**Comparison Query:**
- < 100ms for audits with 50 KPIs each

**Statistics Query:**
- < 30ms for 1,000 audits
- < 200ms for 100,000 audits

---

## Test Checklist

Before marking Phase 2 as complete:

- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Server starts without errors
- [ ] `audits.db` file created
- [ ] Can create audit via API
- [ ] Can retrieve audit after server restart (persistence)
- [ ] Rate limiting works (11th request gets 429)
- [ ] Batch processing creates multiple audits
- [ ] Audit history returns previous audits
- [ ] Audit comparison shows changes
- [ ] Latest audit endpoint works
- [ ] Statistics endpoint returns data
- [ ] Cleanup endpoint deletes old audits
- [ ] Frontend can start and monitor audits
- [ ] Database file grows with new audits

---

## Next Steps After Testing

Once all tests pass:

### Phase 3: Performance Optimization
- Implement Redis caching
- Parallelize KPI extraction
- Add request deduplication
- Optimize database queries

### Phase 4: Advanced Features
- Add user authentication
- Implement API keys
- Schedule periodic audits
- Add webhook notifications

### Production Deployment
- Switch to PostgreSQL
- Set up database backups
- Configure monitoring
- Deploy to cloud (AWS/GCP/Azure)

---

## Support

**Database Issues:** Check [PHASE_2_IMPLEMENTATION.md](PHASE_2_IMPLEMENTATION.md)  
**API Documentation:** `http://localhost:8000/docs`  
**Server Logs:** Check console output for errors  

**Common Commands:**
```powershell
# Check if database exists
Test-Path backend/audits.db

# View database size
(Get-Item backend/audits.db).Length / 1MB

# Clear database (start fresh)
Remove-Item backend/audits.db
python server.py  # Creates new database

# Check Python packages
pip list | Select-String "sqlalchemy|alembic|slowapi"
```
