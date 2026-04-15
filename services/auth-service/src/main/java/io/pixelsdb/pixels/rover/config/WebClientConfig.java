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
package io.pixelsdb.pixels.rover.config;

import io.netty.channel.ChannelOption;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

/**
 * Centralized WebClient configuration with unified timeout settings.
 * <p>
 * All upstream HTTP calls (Metadata Server, Query Server, Text-to-SQL)
 * share the same timeout policy defined here.
 *
 * @author pixels
 */
@Configuration
public class WebClientConfig
{
    /** TCP connection timeout: 5 seconds */
    private static final int CONNECT_TIMEOUT_MS = 5_000;

    /** HTTP response timeout: 30 seconds */
    private static final Duration RESPONSE_TIMEOUT = Duration.ofSeconds(30);

    @Bean
    public WebClient.Builder webClientBuilder()
    {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(RESPONSE_TIMEOUT);

        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient));
    }
}
