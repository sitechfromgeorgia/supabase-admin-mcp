---
name: production-postgresql-supabase-nextjs-setup
description: Configures production-ready PostgreSQL 15+ for Supabase self-hosting with Next.js, including memory tuning, connection pooling, automated backups with WAL-G, disaster recovery, and security hardening. Use when deploying self-hosted Supabase, optimizing database performance under concurrency, setting up PITR, or troubleshooting connection exhaustion errors.
---

# Production PostgreSQL Setup for Supabase & Next.js (2025)

## Quick Start

### Configuration Heuristic (By RAM)

```bash
# Calculate optimal settings based on server RAM
RAM_GB=16
SHARED_BUFFERS=$((RAM_GB * 256 / 4))MB        # 25% of RAM
EFFECTIVE_CACHE_SIZE=$((RAM_GB * 256 * 3 / 4))MB  # 75% of RAM
WORK_MEM=$((RAM_GB * 4))MB                    # 4MB per GB (for 100 connections)
WAL_BUFFERS=16MB                               # 1% of shared_buffers

# For 8GB RAM:  shared_buffers=2GB, effective_cache_size=6GB, work_mem=32MB
# For 16GB RAM: shared_buffers=4GB, effective_cache_size=12GB, work_mem=64MB
# For 32GB RAM: shared_buffers=8GB, effective_cache_size=24GB, work_mem=128MB
```

### Essential Docker Service (Self-Hosted)

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15-alpine
    container_name: supabase-postgres
    restart: always
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: postgres
      POSTGRES_USER: postgres
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgresql.conf:/var/lib/postgresql/data/postgresql.conf
      - ./pg_hba.conf:/var/lib/postgresql/data/pg_hba.conf
      - ./init-db.sql:/docker-entrypoint-initdb.d/01-init.sql
    command: 
      - "postgres"
      - "-c"
      - "config_file=/var/lib/postgresql/data/postgresql.conf"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - supabase-network

  # Optional: Connection pooler for serverless
  pgbouncer:
    image: pgbouncer:latest
    container_name: supabase-pgbouncer
    restart: always
    ports:
      - "6543:6543"
    environment:
      PGBOUNCER_DATABASES: "postgres=host=postgres port=5432 dbname=postgres"
      PGBOUNCER_POOL_MODE: "transaction"  # Use transaction for serverless/edge
      PGBOUNCER_MAX_CLIENT_CONN: 1000
      PGBOUNCER_DEFAULT_POOL_SIZE: 25
      PGBOUNCER_MIN_POOL_SIZE: 5
    volumes:
      - ./pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - supabase-network

networks:
  supabase-network:
    driver: bridge

volumes:
  postgres_data:
```

---

## When to Use This Skill

- Setting up **self-hosted Supabase** with PostgreSQL 15+
- Optimizing database for **high-concurrency Next.js** (Vercel Edge, Serverless)
- Configuring **connection pooling** with Supavisor/PgBouncer
- Implementing **point-in-time recovery (PITR)** with WAL-G
- Troubleshooting **"remaining connection slots reserved"** errors
- Tuning **autovacuum** for large, high-update tables
- Setting up **S3 continuous backups** for disaster recovery

---

## Memory Configuration (postgresql.conf)

### Shared Buffers

**Purpose**: PostgreSQL in-process cache for frequently accessed data blocks.

```ini
# For dedicated DB server, set to 25-40% of total RAM
# Rule: Never allocate entire RAM—OS needs cache space too

# 4GB server
shared_buffers = 1GB

# 8GB server
shared_buffers = 2GB

# 16GB server
shared_buffers = 4GB

# 32GB server
shared_buffers = 8GB
```

**Why this matters**: Larger shared_buffers reduce disk I/O. PostgreSQL processes can read data without querying OS cache. If set too high (>40% RAM), you lose OS-level caching benefits.

### Effective Cache Size

**Purpose**: Helps query planner estimate total available cache (PostgreSQL + OS).

```ini
# Set to ~75% of total RAM (PostgreSQL + OS cache combined)

# 4GB server
effective_cache_size = 3GB

# 8GB server
effective_cache_size = 6GB

# 16GB server
effective_cache_size = 12GB

# 32GB server
effective_cache_size = 24GB
```

**Query planner behavior**: Higher value → more sequential scans become index scans (assumes data is in cache).

### Work Memory

**Purpose**: Per-operation memory (sorts, hash tables, bitmap scans).

```ini
# Formula: (available_RAM - shared_buffers) / max_connections / 2
# For 8GB RAM, 100 connections: (8GB - 2GB) / 100 / 2 ≈ 30MB

# Conservative (stable, predictable)
work_mem = 4MB      # For 8GB, 100 connections

# Moderate (better performance, higher risk if many parallel ops)
work_mem = 32MB     # For 8GB, 50-100 connections

# High concurrency serverless
work_mem = 2MB      # For 8GB, 200+ concurrent operations
```

**Critical**: Total memory used = `work_mem × concurrent_ops`. Underestimate = disk spills. Overestimate = OOM kills.

### WAL Buffers

```ini
# Default 16MB is fine for most workloads
# Only increase if write-heavy (>10K TPS) and disk-bound

wal_buffers = 16MB

# High write volume:
wal_buffers = 64MB
```

---

## Write Performance & Checkpoints (postgresql.conf)

```ini
# Spread writes smoothly instead of sudden I/O spikes
checkpoint_completion_target = 0.9

# Max WAL size before forced checkpoint
# Larger = longer recovery time, smoother writes
# Smaller = faster recovery, more I/O
max_wal_size = 4GB          # For 8-16GB server
max_wal_size = 8GB          # For 32GB+ server

# WAL level for replication + PITR
wal_level = replica

# Archive WAL files continuously (for PITR)
archive_mode = on
archive_command = '/path/to/wal-archive.sh %p %f'

# Replication settings (if using streaming replication)
max_wal_senders = 3
max_replication_slots = 3
wal_keep_size = 1GB
```

---

## Connection Pooling: Supavisor vs PgBouncer

### When PostgreSQL Hits Connection Limits

**Problem**: Each Next.js serverless function spawns new connection → exhausts PostgreSQL's `max_connections` pool.

```
Next.js Edge (Vercel): 10,000 concurrent requests
PostgreSQL max_connections: 100 (default)
Result: FATAL error after 100 connections
```

### Connection Pooler Types

| Mode | Use Case | Limitations |
|------|----------|-------------|
| **Transaction** | Serverless/Edge functions (Next.js) | No prepared statements, no session state |
| **Session** | Persistent backends, long-lived apps | Cannot handle connection surge |
| **Direct** | Microservices needing control | No pooling benefits |

### Supavisor Configuration (Supabase Native)

```yaml
supavisor:
  image: supabase/supavisor:latest
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_PORT: 5432
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    POSTGRES_DB: postgres
    # Transaction mode for serverless
    DEFAULT_POOL_MODE: transaction
    DEFAULT_POOL_SIZE: 25
    DEFAULT_MAX_CLIENT_CONN: 1000
  ports:
    - "5432:5432"   # Session mode
    - "6543:6543"   # Transaction mode
  depends_on:
    - postgres
```

### PgBouncer Configuration (pgbouncer.ini)

```ini
[databases]
postgres = host=postgres port=5432 dbname=postgres user=postgres

[pgbouncer]
# Transaction mode for serverless
pool_mode = transaction

# Pool sizing: (CPU_CORES × 4) to (CPU_CORES × 8)
# For 4 CPUs: 16-32 connections
default_pool_size = 25
min_pool_size = 5
reserve_pool_size = 5

# Client limits
max_client_conn = 1000
max_db_connections = 100

# Timeouts
client_idle_timeout = 600
idle_in_transaction_session_timeout = 0  # Important: 0 = no timeout

# Query log
query_wait_timeout = 120
```

### Connection String Patterns

**Direct (no pooling)**:
```
postgres://postgres:password@db:5432/postgres
```

**Supavisor Transaction (serverless)**:
```
postgres://postgres:password@db:6543/postgres?pgbouncer=true
```

**PgBouncer Transaction**:
```
postgres://postgres:password@localhost:6543/postgres?pgbouncer=true
```

### Prisma + Transaction Mode Setup

```typescript
// prisma.schema or environment setup
// DATABASE_URL uses transaction pooler for queries
// DIRECT_URL uses direct connection for migrations

// .env
DATABASE_URL="postgresql://postgres:password@db:6543/postgres?pgbouncer=true"
DIRECT_URL="postgresql://postgres:password@db:5432/postgres"
```

```typescript
// prisma/client.ts
import { PrismaPg } from '@prisma/adapter-pg'
import { PrismaClient } from '@prisma/client'
import { Pool } from 'pg'

// Transaction pooler for queries
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
})

const adapter = new PrismaPg(pool)
export const prisma = new PrismaClient({ adapter })

// CLI uses DIRECT_URL automatically for migrations
```

### Drizzle + Transaction Mode

```typescript
// lib/db.ts
import { drizzle } from 'drizzle-orm/postgres-js'
import postgres from 'postgres'

// For serverless: use transaction pooler
const client = postgres(process.env.DATABASE_URL!)

export const db = drizzle(client)
```

---

## Autovacuum Tuning for High-Update Tables

### Global Settings (postgresql.conf)

```ini
# More aggressive than defaults (0.20 default)
autovacuum_vacuum_scale_factor = 0.10
autovacuum_vacuum_threshold = 500

autovacuum_analyze_scale_factor = 0.05
autovacuum_analyze_threshold = 500

# For insert-heavy tables (PostgreSQL 13+)
autovacuum_vacuum_insert_scale_factor = 0.10
autovacuum_vacuum_insert_threshold = 100000

# Cost control
autovacuum_vacuum_cost_delay = 2ms      # Default 2ms
autovacuum_vacuum_cost_limit = 1000     # Increase if autovacuum lags
```

**Vacuum trigger formula**: `(row_count × scale_factor) + threshold`

Example: 1M rows, default settings (0.20 + 50):
```
Vacuum triggers after: (1,000,000 × 0.20) + 50 = 200,050 dead rows
```

With aggressive settings (0.10 + 500):
```
Vacuum triggers after: (1,000,000 × 0.10) + 500 = 100,500 dead rows
```

### Per-Table Override (For Problem Tables)

```sql
-- High-update tables (e.g., activity logs, metrics)
ALTER TABLE activity_logs SET (
  autovacuum_vacuum_scale_factor = 0.0,
  autovacuum_vacuum_threshold = 50000,     -- Vacuum after 50K dead rows
  autovacuum_analyze_scale_factor = 0.0,
  autovacuum_analyze_threshold = 10000
);

-- Insert-heavy tables
ALTER TABLE events SET (
  autovacuum_vacuum_insert_scale_factor = 0.0,
  autovacuum_vacuum_insert_threshold = 50000,
  fillfactor = 80  -- Leave 20% space for in-place updates
);
```

### Monitor Autovacuum Health

```sql
-- Find tables with excessive dead tuples
SELECT
  schemaname,
  relname,
  n_dead_tup,
  n_live_tup,
  ROUND(n_dead_tup::float / NULLIF(n_live_tup, 0) * 100, 2) AS dead_ratio,
  last_vacuum,
  last_autovacuum
FROM pg_stat_user_tables
WHERE n_dead_tup > 100000
ORDER BY n_dead_tup DESC;

-- Check current autovacuum processes
SELECT * FROM pg_stat_progress_vacuum;
```

---

## Backup & Disaster Recovery

### WAL-G Continuous Archiving (PITR)

**Prerequisites**: WAL-G binary installed, S3 credentials, PostgreSQL configured.

#### Docker-Compose Setup

```yaml
postgres:
  image: postgres:15-alpine
  environment:
    # WAL-G S3 configuration
    WALG_S3_PREFIX: s3://my-bucket/postgres-backups
    AWS_REGION: us-east-1
    AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
    AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
    WALG_COMPRESSION_METHOD: brotli
    WALG_DELTA_MAX_STEPS: 5  # Create delta backups after N WALs
  volumes:
    - ./backup-script.sh:/usr/local/bin/backup.sh
  command:
    - postgres
    - -c
    - archive_command=/usr/local/bin/wal-archive.sh %p %f
```

#### WAL Archive Script

```bash
#!/bin/bash
# /usr/local/bin/wal-archive.sh

WAL_PATH=$1
WAL_FILE=$2

# Ensure WAL-G installed
if ! command -v wal-g &> /dev/null; then
  echo "wal-g not found, skipping archive"
  exit 1
fi

# Archive to S3
export WALG_S3_PREFIX="${WALG_S3_PREFIX}"
export AWS_REGION="${AWS_REGION}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}"

# Send WAL file
if wal-g wal-push "$WAL_PATH"; then
  exit 0
else
  echo "Failed to archive WAL: $WAL_FILE" >&2
  exit 1
fi
```

#### Base Backup Script

```bash
#!/bin/bash
# backup-full.sh - Run daily via cron

BACKUP_DIR="/var/lib/postgresql/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/postgres-backup-$TIMESTAMP.log"

mkdir -p "$BACKUP_DIR"

export WALG_S3_PREFIX="s3://my-bucket/postgres-backups"
export AWS_REGION="us-east-1"

# Take base backup
echo "Starting base backup at $(date)" >> "$LOG_FILE"

wal-g backup-push /var/lib/postgresql/data >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
  echo "Base backup completed successfully" >> "$LOG_FILE"
  
  # Optional: cleanup old backups (keep 7 days)
  wal-g delete before 7 days > /dev/null 2>&1
else
  echo "Base backup FAILED" >> "$LOG_FILE"
  # Alert ops/send email
fi
```

#### Cron Schedule

```bash
# Daily base backup at 2 AM UTC
0 2 * * * /usr/local/bin/backup-full.sh

# Verify backup integrity weekly
0 3 * * 0 wal-g backup-list | tail -1
```

### Point-in-Time Recovery (PITR)

#### Enable PITR

```ini
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = '/usr/local/bin/wal-archive.sh %p %f'
max_wal_senders = 3
max_replication_slots = 3
wal_keep_size = 1GB
```

#### Recovery Steps

```bash
# 1. Stop PostgreSQL
systemctl stop postgresql

# 2. Create recovery.signal file
touch /var/lib/postgresql/data/recovery.signal

# 3. Edit recovery config in postgresql.conf
cat >> /var/lib/postgresql/data/postgresql.conf <<EOF
recovery_target_time = '2025-01-20 14:30:00 UTC'
recovery_target_action = 'promote'
restore_command = 'wal-g wal-fetch %f %p'
recovery_target_inclusive = true
EOF

# 4. Start PostgreSQL (auto-recovery triggers)
systemctl start postgresql

# 5. Verify recovery
psql -U postgres -c "SELECT now();"
```

---

## Security: HBA Configuration

### pg_hba.conf (Host-Based Access Control)

```ini
# Docker network internal - allow without password
host    all             all             172.16.0.0/12  trust
host    all             all             127.0.0.1/32   trust

# Localhost - md5 password
local   all             all                             md5

# Reject public internet
host    all             all             0.0.0.0/0       reject
host    all             all             ::/0            reject

# Replication connections (internal only)
host    replication     all             172.16.0.0/12   md5
```

### Docker Network Isolation

```yaml
services:
  postgres:
    networks:
      - backend
    # No ports exposed (internal-only)

networks:
  backend:
    driver: bridge
    driver_opts:
      com.docker.network.driver.mtu: 1450

  # Next.js connects to postgres:5432 (internal DNS)
  # External access: blocked by default
```

---

## Troubleshooting

### FATAL: remaining connection slots reserved for non-replication superuser

**Causes**:
1. Next.js creating too many connections (serverless surge)
2. Connection pooler not configured
3. Stale connections not released

**Solutions**:

```sql
-- Check current connections
SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- Kill idle connections
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
AND query_start < now() - interval '10 minutes';
```

**Immediate fix**: Use transaction pooler (Supavisor/PgBouncer)

```env
# Switch to pooled connection
DATABASE_URL="postgresql://postgres:password@pooler:6543/postgres?pgbouncer=true"
```

### High Autovacuum CPU Usage

**Symptom**: CPU spike during autovacuum, slow queries.

**Fix**:

```ini
# postgresql.conf - reduce vacuum cost
autovacuum_vacuum_cost_delay = 10ms   # Slower, less CPU
autovacuum_vacuum_cost_limit = 500    # Lower limit = spread work out

# Or disable for specific low-priority tables
ALTER TABLE archive_data SET (autovacuum_enabled = false);
```

### Checkpoint Stalls (fsync wait)

**Symptom**: Checkpoint takes 30+ seconds, queries pause.

**Fix**:

```ini
# Spread checkpoints over 9 minutes instead of 5
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9

# Increase max_wal_size
max_wal_size = 8GB
```

### Query Planner Choosing Wrong Index

**Symptom**: Sequential scan when index available, slow queries.

**Fix**:

```sql
-- Update table stats
ANALYZE table_name;

-- Check estimated vs actual rows
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 123;
```

---

## References

- [PostgreSQL Memory Tuning](https://www.enterprisedb.com/postgres-tutorials/how-tune-postgresql-memory)
- [Supabase Connection Pooling](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supavisor GitHub](https://github.com/supabase/supavisor)
- [WAL-G Documentation](https://wal-g.readthedocs.io/)
- [PostgreSQL PITR Guide](https://www.postgresql.org/docs/current/continuous-archiving.html)
- [Autovacuum Tuning Best Practices](https://www.percona.com/blog/importance-of-postgresql-vacuum-tuning-and-custom-scheduled-vacuum-job/)
- [Prisma + Supabase](https://www.prisma.io/docs/orm/overview/databases/supabase)
- [PgBouncer Configuration](https://www.pgbouncer.org/config.html)
