/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.pixelsdb.pixels.rover.constant;

/**
 * REST API URL path constants with /api/v1/ prefix.
 *
 * @author pixels
 */
public class RestUrlPath
{
    // Metadata API paths
    public static final String GET_SCHEMAS = "/api/v1/metadata/get-schemas";
    public static final String GET_TABLES = "/api/v1/metadata/get-tables";
    public static final String GET_COLUMNS = "/api/v1/metadata/get-columns";
    public static final String GET_VIEWS = "/api/v1/metadata/get-views";

    // Query API paths
    public static final String ESTIMATE_QUERY_COST = "/api/v1/query/estimate-query-cost";
    public static final String SUBMIT_QUERY = "/api/v1/query/submit-query";
    public static final String GET_QUERY_STATUS = "/api/v1/query/get-query-status";
    public static final String GET_QUERY_RESULT = "/api/v1/query/get-query-result";

    // Text-to-SQL API path
    public static final String TEXT_TO_SQL = "/api/v1/query/text-to-sql";

    // Upstream paths (used when forwarding to Pixels Server)
    public static final String UPSTREAM_GET_SCHEMAS = "/api/metadata/get-schemas";
    public static final String UPSTREAM_GET_TABLES = "/api/metadata/get-tables";
    public static final String UPSTREAM_GET_COLUMNS = "/api/metadata/get-columns";
    public static final String UPSTREAM_GET_VIEWS = "/api/metadata/get-views";
    public static final String UPSTREAM_SUBMIT_QUERY = "/api/query/submit-query";
    public static final String UPSTREAM_GET_QUERY_STATUS = "/api/query/get-query-status";
    public static final String UPSTREAM_GET_QUERY_RESULT = "/api/query/get-query-result";
}
