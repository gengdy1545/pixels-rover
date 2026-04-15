-- Create the MySQL database for pixels-rover.

SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- -----------------------------------------------------
-- Schema pixels_rover
-- -----------------------------------------------------

-- -----------------------------------------------------
-- Schema pixels_rover
-- -----------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `pixels_rover` DEFAULT CHARACTER SET utf8 COLLATE utf8_bin ;
USE `pixels_rover` ;

-- -----------------------------------------------------
-- Table `pixels_rover`.`user`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `pixels_rover`.`user` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(128) CHARACTER SET 'utf8mb4' COLLATE 'utf8mb4_bin' NOT NULL,
    `email` VARCHAR(128) CHARACTER SET 'utf8mb4' COLLATE 'utf8mb4_bin' NOT NULL,
    `affiliation` VARCHAR(128) CHARACTER SET 'utf8mb4' COLLATE 'utf8mb4_bin' NOT NULL,
    `password` VARCHAR(64) CHARACTER SET 'utf8mb4' COLLATE 'utf8mb4_bin' NOT NULL,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `email_UNIQUE` (`email` ASC) VISIBLE)
    ENGINE = InnoDB
    DEFAULT CHARACTER SET = utf8
    COLLATE = utf8_bin;

-- -----------------------------------------------------
-- Table `pixels_rover`.`sql_statements`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `pixels_rover`.`sql_statements` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `uuid` VARCHAR(36) NOT NULL,
    `sql_text` TEXT NOT NULL,
    `is_modified` BOOLEAN DEFAULT FALSE,
    `is_executed` BOOLEAN DEFAULT FALSE,
    `create_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uuid_UNIQUE` (`uuid` ASC) VISIBLE)
    ENGINE = InnoDB
    DEFAULT CHARACTER SET = utf8
    COLLATE = utf8_bin;

-- -----------------------------------------------------
-- Table `pixels_rover`.`messages`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `pixels_rover`.`messages` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_message` TEXT NOT NULL,
    `user_message_uuid` VARCHAR(36) NOT NULL,
    `sql_statements_uuid` VARCHAR(36) NOT NULL,
    `create_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`))
    ENGINE = InnoDB
    DEFAULT CHARACTER SET = utf8
    COLLATE = utf8_bin;

-- -----------------------------------------------------
-- Table `pixels_rover`.`query_results`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `pixels_rover`.`query_results` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `sql_statements_uuid` VARCHAR(36) NOT NULL,
    `result` TEXT NOT NULL,
    `result_limit` BIGINT NOT NULL,
    `result_uuid` VARCHAR(36) NOT NULL,
    `create_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`))
    ENGINE = InnoDB
    DEFAULT CHARACTER SET = utf8
    COLLATE = utf8_bin;

-- -----------------------------------------------------
-- Table `pixels_rover`.`auth_session`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `pixels_rover`.`auth_session` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `session_id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `user_email` VARCHAR(128) CHARACTER SET 'utf8mb4' COLLATE 'utf8mb4_bin' NOT NULL,
    `refresh_token_hash` VARCHAR(64) NOT NULL,
    `current_refresh_token_id` VARCHAR(36) NOT NULL,
    `refresh_token_expires_at` TIMESTAMP NOT NULL,
    `last_activity_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `user_agent` VARCHAR(255) NULL,
    `client_ip` VARCHAR(64) NULL,
    `revoked_at` TIMESTAMP NULL,
    `revoked_reason` VARCHAR(128) NULL,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uk_auth_session_session_id` (`session_id` ASC) VISIBLE,
    INDEX `idx_auth_session_user_id` (`user_id` ASC) VISIBLE,
    CONSTRAINT `fk_auth_session_user`
        FOREIGN KEY (`user_id`)
        REFERENCES `pixels_rover`.`user` (`id`)
        ON DELETE CASCADE
        ON UPDATE CASCADE)
    ENGINE = InnoDB
    DEFAULT CHARACTER SET = utf8
    COLLATE = utf8_bin;

SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
