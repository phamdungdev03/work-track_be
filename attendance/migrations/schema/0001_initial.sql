-- WorkTrack: 10-table demo schema. MySQL >= 8.0.16; target 8.4.
-- Run ONCE on an EMPTY database: mysql -u USER -p worktrack < database/attendance-schema.sql
-- This is initial DDL, NOT an upgrade from the previous 22-table schema.
-- No DROP, seed data, credentials, or FK bypass. DDL implicitly commits.
-- Store DATETIME in UTC; configure every application connection accordingly.
-- Backend implements auto IN/OUT, cooldown, QR/GPS checks, approvals and calculation.
-- Scans/audit are append-only by application grants; approved requests are immutable.
SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET SESSION time_zone = '+00:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';


CREATE TABLE facilities (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(200) NOT NULL,
    address VARCHAR(500) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    latitude DECIMAL(10,7) NULL,
    longitude DECIMAL(10,7) NULL,
    geofence_radius_m INT UNSIGNED NULL,
    qr_ttl_seconds SMALLINT UNSIGNED NOT NULL DEFAULT 20,
    max_location_age_seconds INT UNSIGNED NULL,
    max_location_accuracy_m INT UNSIGNED NULL,
    min_scan_interval_seconds SMALLINT UNSIGNED NOT NULL DEFAULT 10,
    policy_revision INT UNSIGNED NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_facilities_code (code),
    CONSTRAINT ck_facilities_1 CHECK (is_active IN (0,1)),
    CONSTRAINT ck_facilities_2 CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_facilities_3 CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_facilities_4 CHECK ((latitude IS NULL AND longitude IS NULL AND geofence_radius_m IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND geofence_radius_m IS NOT NULL AND geofence_radius_m > 0)),
    CONSTRAINT ck_facilities_5 CHECK (qr_ttl_seconds > 0),
    CONSTRAINT ck_facilities_6 CHECK (max_location_age_seconds > 0),
    CONSTRAINT ck_facilities_7 CHECK (max_location_accuracy_m > 0),
    CONSTRAINT ck_facilities_8 CHECK (min_scan_interval_seconds BETWEEN 1 AND 300),
    CONSTRAINT ck_facilities_9 CHECK (policy_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE employees (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_code VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    hired_on DATE NOT NULL,
    ended_on DATE NULL,
    status VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    home_facility_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_employees_home_facility_id FOREIGN KEY (home_facility_id) REFERENCES facilities(id),
    UNIQUE KEY uq_employees_code (employee_code),
    CONSTRAINT ck_employees_1 CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_employees_2 CHECK (ended_on IS NULL OR ended_on >= hired_on)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    login_name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    employee_id BIGINT UNSIGNED NULL,
    CONSTRAINT fk_users_employee_id FOREIGN KEY (employee_id) REFERENCES employees(id),
    UNIQUE KEY uq_users_login (login_name),
    UNIQUE KEY uq_users_employee (employee_id),
    CONSTRAINT ck_users_1 CHECK (role IN ('EMPLOYEE', 'MANAGER', 'HR', 'ADMIN')),
    CONSTRAINT ck_users_2 CHECK (is_active IN (0,1)),
    CONSTRAINT ck_users_3 CHECK (role NOT IN ('EMPLOYEE','MANAGER') OR employee_id IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE work_schedules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT UNSIGNED NOT NULL,
    owner_facility_id BIGINT UNSIGNED NOT NULL,
    work_date DATE NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    starts_at DATETIME(6) NOT NULL,
    ends_at DATETIME(6) NOT NULL,
    standard_work_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 480,
    unpaid_break_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
    policy_snapshot JSON NOT NULL,
    status VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'SCHEDULED',
    revision INT UNSIGNED NOT NULL DEFAULT 1,
    locked_at DATETIME(6) NULL,
    locked_by BIGINT UNSIGNED NULL,
    locked_result JSON NULL,
    created_by BIGINT UNSIGNED NULL,
    UNIQUE KEY uq_schedule_employee_date (employee_id, work_date),
    KEY ix_schedule_facility_date (owner_facility_id, work_date),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (owner_facility_id) REFERENCES facilities(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (locked_by) REFERENCES users(id),
    CONSTRAINT ck_schedule_status CHECK (status IN ('SCHEDULED','CANCELLED')),
    CONSTRAINT ck_schedule_duration CHECK (starts_at < ends_at AND standard_work_minutes > 0 AND (standard_work_minutes + unpaid_break_minutes) * 60 <= TIMESTAMPDIFF(SECOND, starts_at, ends_at)),
    CONSTRAINT ck_schedule_revision CHECK (revision > 0),
    CONSTRAINT ck_schedule_lock CHECK ((locked_at IS NULL AND locked_by IS NULL AND locked_result IS NULL) OR (locked_at IS NOT NULL AND locked_by IS NOT NULL AND locked_result IS NOT NULL)),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE support_assignments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    depart_at DATETIME(6) NOT NULL,
    expected_arrival_at DATETIME(6) NOT NULL,
    support_ends_at DATETIME(6) NOT NULL,
    status VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'PLANNED',
    reason VARCHAR(1000) NOT NULL,
    confirmed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    schedule_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_support_assignments_schedule_id FOREIGN KEY (schedule_id) REFERENCES work_schedules(id),
    from_facility_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_support_assignments_from_facility_id FOREIGN KEY (from_facility_id) REFERENCES facilities(id),
    to_facility_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_support_assignments_to_facility_id FOREIGN KEY (to_facility_id) REFERENCES facilities(id),
    created_by BIGINT UNSIGNED NULL,
    client_request_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NULL,
    creation_hash BINARY(32) NULL,
    CONSTRAINT fk_support_assignments_created_by FOREIGN KEY (created_by) REFERENCES users(id),
    confirmed_by BIGINT UNSIGNED NULL,
    CONSTRAINT fk_support_assignments_confirmed_by FOREIGN KEY (confirmed_by) REFERENCES users(id),
    KEY ix_support_schedule (schedule_id, depart_at),
    UNIQUE KEY uq_support_client_request (client_request_id),
    CONSTRAINT ck_support_creation_key CHECK ((client_request_id IS NULL AND creation_hash IS NULL) OR (client_request_id IS NOT NULL AND creation_hash IS NOT NULL)),
    CONSTRAINT ck_support_assignments_1 CHECK (status IN ('PLANNED', 'CONFIRMED', 'CANCELLED')),
    CONSTRAINT ck_support_assignments_2 CHECK (from_facility_id <> to_facility_id),
    CONSTRAINT ck_support_assignments_3 CHECK (depart_at <= expected_arrival_at AND expected_arrival_at < support_ends_at),
    CONSTRAINT ck_support_assignments_4 CHECK (confirmed_by IS NULL OR confirmed_at IS NOT NULL),
    CONSTRAINT ck_support_assignments_5 CHECK (status <> 'CONFIRMED' OR confirmed_at IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE qr_challenges (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nonce_hash BINARY(32) NOT NULL,
    issued_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    policy_snapshot JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    facility_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_qr_challenges_facility_id FOREIGN KEY (facility_id) REFERENCES facilities(id),
    issued_by BIGINT UNSIGNED NULL,
    CONSTRAINT fk_qr_challenges_issued_by FOREIGN KEY (issued_by) REFERENCES users(id),
    UNIQUE KEY uq_qr_nonce (nonce_hash),
    KEY ix_qr_facility_expiry (facility_id, expires_at),
    CONSTRAINT ck_qr_challenges_1 CHECK (issued_at < expires_at),
    CONSTRAINT ck_qr_challenges_2 CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE attendance_alerts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    work_date DATE NOT NULL,
    alert_type VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'OPEN',
    first_seen_at DATETIME(6) NOT NULL,
    last_seen_at DATETIME(6) NOT NULL,
    verified_at DATETIME(6) NULL,
    review_note VARCHAR(1000) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    employee_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_attendance_alerts_employee_id FOREIGN KEY (employee_id) REFERENCES employees(id),
    facility_id BIGINT UNSIGNED NOT NULL,
    CONSTRAINT fk_attendance_alerts_facility_id FOREIGN KEY (facility_id) REFERENCES facilities(id),
    verified_by BIGINT UNSIGNED NULL,
    CONSTRAINT fk_attendance_alerts_verified_by FOREIGN KEY (verified_by) REFERENCES users(id),
    UNIQUE KEY uq_alerts_case (employee_id, work_date, facility_id, alert_type),
    KEY ix_alerts_queue (status, work_date),
    CONSTRAINT ck_attendance_alerts_1 CHECK (status IN ('OPEN', 'VERIFIED')),
    CONSTRAINT ck_attendance_alerts_2 CHECK (first_seen_at <= last_seen_at),
    CONSTRAINT ck_attendance_alerts_3 CHECK ((status = 'OPEN' AND verified_by IS NULL AND verified_at IS NULL) OR (status = 'VERIFIED' AND verified_at IS NOT NULL AND review_note IS NOT NULL AND CHAR_LENGTH(TRIM(review_note)) > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE attendance_scans (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT UNSIGNED NULL,
    facility_id BIGINT UNSIGNED NOT NULL,
    actor_user_id BIGINT UNSIGNED NULL,
    source_type VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_event_id VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload_hash BINARY(32) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    received_at DATETIME(6) NOT NULL,
    outcome VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_type VARCHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
    reason_code VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    decision_snapshot JSON NOT NULL,
    latitude DECIMAL(10,7) NULL,
    longitude DECIMAL(10,7) NULL,
    accuracy_m DECIMAL(10,2) NULL,
    location_observed_at DATETIME(6) NULL,
    qr_challenge_id BIGINT UNSIGNED NULL,
    alert_id BIGINT UNSIGNED NULL,
    -- Only accepted QR scans consume the token; rejected attempts remain repeatable.
    consumed_qr_id BIGINT UNSIGNED GENERATED ALWAYS AS
        (CASE WHEN outcome = 'ACCEPTED' AND source_type = 'MOBILE_QR' THEN qr_challenge_id ELSE NULL END) STORED,
    UNIQUE KEY uq_scan_source_event (source_key, source_event_id),
    UNIQUE KEY uq_scan_qr_employee (consumed_qr_id, employee_id),
    KEY ix_scan_employee_time (employee_id, occurred_at, id),
    KEY ix_scan_facility_time (facility_id, occurred_at),
    KEY ix_scan_outcome_time (outcome, received_at),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (facility_id) REFERENCES facilities(id),
    FOREIGN KEY (actor_user_id) REFERENCES users(id),
    FOREIGN KEY (qr_challenge_id) REFERENCES qr_challenges(id),
    FOREIGN KEY (alert_id) REFERENCES attendance_alerts(id),
    CONSTRAINT ck_scan_source CHECK (source_type IN ('FACE_DEVICE','MOBILE_QR','DEMO')),
    CONSTRAINT ck_scan_outcome CHECK (outcome IN ('ACCEPTED','IGNORED','REJECTED','PENDING_REVIEW')),
    CONSTRAINT ck_scan_direction CHECK ((outcome = 'ACCEPTED' AND employee_id IS NOT NULL AND event_type IS NOT NULL AND event_type IN ('IN','OUT')) OR (outcome <> 'ACCEPTED' AND event_type IS NULL)),
    CONSTRAINT ck_scan_pending CHECK (outcome <> 'PENDING_REVIEW' OR employee_id IS NOT NULL),
    CONSTRAINT ck_scan_mobile CHECK (source_type <> 'MOBILE_QR' OR outcome <> 'ACCEPTED' OR qr_challenge_id IS NOT NULL),
    CONSTRAINT ck_scan_alert CHECK (alert_id IS NULL OR outcome = 'ACCEPTED'),
    CONSTRAINT ck_scan_lat CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_scan_lon CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_scan_coords CHECK ((latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL)),
    CONSTRAINT ck_scan_accuracy CHECK (accuracy_m >= 0),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE attendance_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT UNSIGNED NOT NULL,
    schedule_id BIGINT UNSIGNED NULL,
    requested_by BIGINT UNSIGNED NULL,
    request_type VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_scan_id BIGINT UNSIGNED NULL,
    origin_scan_id BIGINT UNSIGNED NULL,
    proposed_event_type VARCHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
    proposed_facility_id BIGINT UNSIGNED NULL,
    proposed_occurred_at DATETIME(6) NULL,
    reason VARCHAR(1000) NOT NULL,
    status VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'PENDING',
    reviewed_by BIGINT UNSIGNED NULL,
    reviewed_at DATETIME(6) NULL,
    review_note VARCHAR(1000) NULL,
    version INT UNSIGNED NOT NULL DEFAULT 1,
    -- Multiple rejected/pending requests may refer to a scan, only one approved correction.
    approved_target_scan_id BIGINT UNSIGNED GENERATED ALWAYS AS
        (CASE WHEN status = 'APPROVED' THEN target_scan_id ELSE NULL END) STORED,
    UNIQUE KEY uq_request_approved_target (approved_target_scan_id),
    UNIQUE KEY uq_request_origin (origin_scan_id),
    KEY ix_request_schedule_status (schedule_id, status),
    KEY ix_request_queue (status, created_at),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (schedule_id) REFERENCES work_schedules(id),
    FOREIGN KEY (requested_by) REFERENCES users(id),
    FOREIGN KEY (target_scan_id) REFERENCES attendance_scans(id),
    FOREIGN KEY (origin_scan_id) REFERENCES attendance_scans(id),
    FOREIGN KEY (proposed_facility_id) REFERENCES facilities(id),
    FOREIGN KEY (reviewed_by) REFERENCES users(id),
    CONSTRAINT ck_request_requester CHECK (request_type = 'PRESENCE' OR requested_by IS NOT NULL),
    CONSTRAINT ck_request_status CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED')),
    CONSTRAINT ck_request_type CHECK (request_type IN ('ADD_EVENT','REPLACE_EVENT','VOID_EVENT','PRESENCE')),
    CONSTRAINT ck_request_direction CHECK (proposed_event_type IN ('IN','OUT')),
    CONSTRAINT ck_request_shape CHECK (
        (request_type = 'ADD_EVENT' AND target_scan_id IS NULL AND origin_scan_id IS NULL AND proposed_event_type IS NOT NULL AND proposed_facility_id IS NOT NULL AND proposed_occurred_at IS NOT NULL)
        OR (request_type = 'PRESENCE' AND target_scan_id IS NULL AND origin_scan_id IS NOT NULL AND proposed_event_type IS NOT NULL AND proposed_facility_id IS NOT NULL AND proposed_occurred_at IS NOT NULL)
        OR (request_type = 'REPLACE_EVENT' AND target_scan_id IS NOT NULL AND origin_scan_id IS NULL AND proposed_event_type IS NOT NULL AND proposed_facility_id IS NOT NULL AND proposed_occurred_at IS NOT NULL)
        OR (request_type = 'VOID_EVENT' AND target_scan_id IS NOT NULL AND origin_scan_id IS NULL AND proposed_event_type IS NULL AND proposed_facility_id IS NULL AND proposed_occurred_at IS NULL)),
    CONSTRAINT ck_request_review CHECK (
        (status IN ('PENDING','CANCELLED') AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (status IN ('APPROVED','REJECTED') AND reviewed_at IS NOT NULL AND review_note IS NOT NULL AND CHAR_LENGTH(TRIM(review_note)) > 0)),
    CONSTRAINT ck_request_schedule CHECK (status <> 'APPROVED' OR schedule_id IS NOT NULL OR request_type = 'PRESENCE'),
    CONSTRAINT ck_request_reason CHECK (CHAR_LENGTH(TRIM(reason)) > 0),
    CONSTRAINT ck_request_version CHECK (version > 0),
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE audit_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_type VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    action VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    entity_type VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    entity_id BIGINT UNSIGNED NOT NULL,
    before_data JSON NULL,
    after_data JSON NULL,
    reason VARCHAR(1000) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    actor_user_id BIGINT UNSIGNED NULL,
    CONSTRAINT fk_audit_logs_actor_user_id FOREIGN KEY (actor_user_id) REFERENCES users(id),
    KEY ix_audit_entity (entity_type, entity_id, created_at),
    KEY ix_audit_actor (actor_user_id, created_at),
    CONSTRAINT ck_audit_logs_1 CHECK (actor_type IN ('USER', 'SYSTEM')),
    CONSTRAINT ck_audit_logs_2 CHECK ((actor_type = 'USER' AND actor_user_id IS NOT NULL) OR (actor_type = 'SYSTEM' AND actor_user_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
