-- Pixels Rover — MySQL initdb.d schema seed.
--
-- Scope (see docs/development/backend.md §12.1):
--   * This file ONLY creates logical databases (MySQL calls them "schemas")
--     and grants access to the application user.
--   * It MUST NOT declare any CREATE TABLE / ALTER TABLE / INSERT — application
--     table ownership belongs to each service's own migration tool (Alembic for
--     Python services, Flyway for Java services; see backend.md §12.2).
--   * MySQL executes /docker-entrypoint-initdb.d/*.sql ONLY on the first
--     initialization of the data volume. Anything beyond one-shot logical-db
--     creation must go through service migrations.

SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- -----------------------------------------------------
-- Logical database: pixels_auth (owned by auth-service; tables managed by Flyway)
-- -----------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `pixels_auth` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

-- -----------------------------------------------------
-- Logical database: pixels_analysis (owned by assistant-service; tables managed by Alembic)
-- -----------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `pixels_analysis` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

-- -----------------------------------------------------
-- Application user grants
-- -----------------------------------------------------
GRANT ALL PRIVILEGES ON `pixels_auth`.* TO 'pixels'@'%';
GRANT ALL PRIVILEGES ON `pixels_analysis`.* TO 'pixels'@'%';

SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
