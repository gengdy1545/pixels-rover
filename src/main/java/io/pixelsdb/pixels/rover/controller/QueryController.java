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

import io.pixelsdb.pixels.common.server.rest.request.GetQueryResultRequest;
import io.pixelsdb.pixels.common.server.rest.request.GetQueryStatusRequest;
import io.pixelsdb.pixels.common.server.rest.request.SubmitQueryRequest;
import io.pixelsdb.pixels.common.server.rest.response.GetQueryResultResponse;
import io.pixelsdb.pixels.common.server.rest.response.GetQueryStatusResponse;
import io.pixelsdb.pixels.common.server.rest.response.SubmitQueryResponse;
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
public class QueryController
{
    private final WebClient webClient;

    @Autowired
    public QueryController(WebClient.Builder webClientBuilder, @Value("${pixels.server.port}") int port)
    {
        String host = ConfigFactory.Instance().getProperty("metadata.server.host");
        assert (host != null);
        String BASE_URL = "http://" + host + ":" + port;
        this.webClient = webClientBuilder.baseUrl(BASE_URL).build();
    }

    @PostMapping(value = RestUrlPath.SUBMIT_QUERY,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<SubmitQueryResponse> submitQuery(@RequestBody SubmitQueryRequest request)
    {
        try
        {
            SubmitQueryResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_SUBMIT_QUERY)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), SubmitQueryRequest.class)
                    .retrieve()
                    .bodyToMono(SubmitQueryResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }

    @PostMapping(value = RestUrlPath.GET_QUERY_STATUS,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetQueryStatusResponse> getQueryStatus(@RequestBody GetQueryStatusRequest request)
    {
        try
        {
            GetQueryStatusResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_QUERY_STATUS)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetQueryStatusRequest.class)
                    .retrieve()
                    .bodyToMono(GetQueryStatusResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }

    @PostMapping(value = RestUrlPath.GET_QUERY_RESULT,
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<GetQueryResultResponse> getQueryResult(@RequestBody GetQueryResultRequest request)
    {
        try
        {
            GetQueryResultResponse response = webClient.post()
                    .uri(RestUrlPath.UPSTREAM_GET_QUERY_RESULT)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Mono.just(request), GetQueryResultRequest.class)
                    .retrieve()
                    .bodyToMono(GetQueryResultResponse.class)
                    .block();
            return ApiResponse.success(response);
        }
        catch (Exception e)
        {
            return ApiResponse.error(e.getMessage());
        }
    }
}