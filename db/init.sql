-- db/init.sql
CREATE TABLE IF NOT EXISTS bw_devices (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    label       VARCHAR(128) DEFAULT '',
    ip_addr     VARCHAR(64)  NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ip (ip_addr)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bw_sw_revisions (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    revision    VARCHAR(128) NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rev (revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bw_boots (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    device_id    INT NOT NULL,
    revision_id  INT NOT NULL,
    boot_time_s  FLOAT NOT NULL,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source       ENUM('ssh_pull','boot_hook') DEFAULT 'ssh_pull',
    raw_blame    TEXT,
    raw_chain    TEXT,
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id)      ON DELETE CASCADE,
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id) ON DELETE RESTRICT,
    INDEX idx_boots_device_date (device_id, collected_at),
    INDEX idx_boots_revision (revision_id),
    INDEX idx_boots_collected (collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bw_blame_entries (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    boot_id  INT NOT NULL,
    service  VARCHAR(256) NOT NULL,
    time_s   FLOAT NOT NULL,
    FOREIGN KEY (boot_id) REFERENCES bw_boots(id) ON DELETE CASCADE,
    INDEX idx_blame_boot    (boot_id),
    INDEX idx_blame_service (service(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bw_perf_stats (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    device_id       INT NOT NULL,
    revision_id     INT NOT NULL,
    collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s      INT NOT NULL DEFAULT 10,
    cycles          BIGINT,
    instructions    BIGINT,
    ipc             FLOAT,
    cache_misses    BIGINT,
    cache_refs      BIGINT,
    cache_miss_pct  FLOAT,
    branch_misses   BIGINT,
    branch_total    BIGINT,
    branch_miss_pct FLOAT,
    raw_output      TEXT,
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id)      ON DELETE CASCADE,
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id) ON DELETE RESTRICT,
    INDEX idx_perf_device_rev_date (device_id, revision_id, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bw_flamegraphs (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    device_id      INT NOT NULL,
    revision_id    INT NOT NULL,
    generated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration_s     INT NOT NULL DEFAULT 15,
    svg_path       VARCHAR(512),
    perf_data_path VARCHAR(512),
    status         ENUM('pending','running','done','failed') DEFAULT 'pending',
    FOREIGN KEY (device_id)   REFERENCES bw_devices(id)      ON DELETE CASCADE,
    FOREIGN KEY (revision_id) REFERENCES bw_sw_revisions(id) ON DELETE RESTRICT,
    INDEX idx_fg_device_status (device_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
