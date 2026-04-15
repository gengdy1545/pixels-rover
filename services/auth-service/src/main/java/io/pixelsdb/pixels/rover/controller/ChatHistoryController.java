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

import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.model.MessageDetail;
import io.pixelsdb.pixels.rover.model.QueryResults;
import io.pixelsdb.pixels.rover.rest.request.*;
import io.pixelsdb.pixels.rover.service.ChatService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/chat")
public class ChatHistoryController
{
    @Autowired
    private ChatService chatService;

    @PostMapping("/save-sql")
    public ApiResponse<?> saveSQLStatement(@RequestBody SaveSQLRequest request)
    {
        chatService.saveSQLStatement(request.getUuid(), request.getSqlText());
        return ApiResponse.success();
    }

    @PutMapping("/update-sql")
    public ApiResponse<?> updateSQLStatement(@RequestBody UpdateSQLRequest request)
    {
        chatService.updateSQLStatement(request.getUuid(), request.getNewSQL());
        return ApiResponse.success();
    }

    @PostMapping("/get-sql")
    public ApiResponse<String> getSQLStatement(@RequestBody GetSQLRequest request)
    {
        String sql = chatService.getSQLStatement(request.getUuid());
        return ApiResponse.success(sql);
    }

    @PostMapping("/save-message")
    public ApiResponse<?> saveMessage(@RequestBody SaveMessageRequest request)
    {
        chatService.saveMessage(request.getUuid(), request.getSqlText(), request.getUserMessage(), request.getUserMessageUuid());
        return ApiResponse.success();
    }

    @PostMapping("/save-query-result")
    public ApiResponse<?> saveQueryResult(@RequestBody SaveQueryResultRequest request)
    {
        chatService.saveQueryResult(request.getUuid(), request.getResult(), request.getResultLimit(), request.getResultUuid());
        return ApiResponse.success();
    }

    @GetMapping("/history")
    public ApiResponse<List<MessageDetail>> getAllMessagesWithDetails()
    {
        List<MessageDetail> detailList = chatService.getAllMessageWithDetails();
        return ApiResponse.success(detailList);
    }

    @GetMapping("/query-results")
    public ApiResponse<List<QueryResults>> getAllResultsOrderByTimeStamp()
    {
        List<QueryResults> queryResultsList = chatService.getAllQueryResultsOrderByTimestamp();
        return ApiResponse.success(queryResultsList);
    }

    @PostMapping("/query-results-between")
    public ApiResponse<List<QueryResults>> getResultsBetweenTimeStamp(@RequestBody GetQueryResultsBetweenRequest request)
    {
        List<QueryResults> queryResults = chatService.getQueryResultsBetween(request.getStartTime(), request.getEndTime());
        return ApiResponse.success(queryResults);
    }
}
