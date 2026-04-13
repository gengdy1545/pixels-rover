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
package io.pixelsdb.pixels.rover.controller;

import io.pixelsdb.pixels.common.server.rest.request.GetColumnsRequest;
import io.pixelsdb.pixels.common.server.rest.request.GetSchemasRequest;
import io.pixelsdb.pixels.common.server.rest.request.GetTablesRequest;
import io.pixelsdb.pixels.common.server.rest.request.GetViewsRequest;
import io.pixelsdb.pixels.common.server.rest.response.GetColumnsResponse;
import io.pixelsdb.pixels.common.server.rest.response.GetSchemasResponse;
import io.pixelsdb.pixels.common.server.rest.response.GetTablesResponse;
import io.pixelsdb.pixels.common.server.rest.response.GetViewsResponse;
import io.pixelsdb.pixels.common.utils.ConfigFactory;
import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.constant.RestUrlPath;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@RestController
public class MetadataController
{
    private final WebClient webClient;

    @Autowired
    public MetadataController(WebClient.Builder webClientBuilder, @Value("${pixels.server.port}") int port)
    {
        String host = ConfigFactory.Instance().getProperty("metadata.server.host");
        assert (host != null);
        String BASE_URL = "http://" + host + ":" + port;
        this.webClient = webClientBuilder.baseUrl(BASE_URL).build();
    }

    @PostMapping(value = RestUrlPath.GET_SCHEMAS,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetSchemasResponse> getSchemas(@RequestBody GetSchemasRequest request)
    {
        try
        {
            GetSchemasResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_SCHEMAS)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetSchemasRequest.class)
                    .retrieve()
                    .bodyToMono(GetSchemasResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }

    @PostMapping(value = RestUrlPath.GET_TABLES,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetTablesResponse> getTables(@RequestBody GetTablesRequest request)
    {
        try
        {
            GetTablesResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_TABLES)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetTablesRequest.class)
                    .retrieve()
                    .bodyToMono(GetTablesResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }

    @PostMapping(value = RestUrlPath.GET_COLUMNS,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetColumnsResponse> getColumns(@RequestBody GetColumnsRequest request)
    {
        try
        {
            GetColumnsResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_COLUMNS)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetColumnsRequest.class)
                    .retrieve()
                    .bodyToMono(GetColumnsResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }

    @PostMapping(value = RestUrlPath.GET_VIEWS,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetViewsResponse> getViews(@RequestBody GetViewsRequest request)
    {
        try
        {
            GetViewsResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_VIEWS)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetViewsRequest.class)
                    .retrieve()
                    .bodyToMono(GetViewsResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }
}
