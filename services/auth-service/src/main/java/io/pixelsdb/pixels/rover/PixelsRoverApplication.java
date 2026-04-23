/*
 * Copyright 2023 PixelsDB.
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
package io.pixelsdb.pixels.rover;

import io.pixelsdb.pixels.rover.bootstrap.RequiredEnvValidator;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class PixelsRoverApplication
{
	public static void main(String[] args)
	{
		// RequiredEnvValidator (§14) is intentionally attached ONLY here —
		// Spring's test infrastructure creates its own SpringApplication
		// without invoking main(), so @SpringBootTest / @WebMvcTest contexts
		// skip the validator and continue to load on empty-default
		// placeholders. Production boot (container ENTRYPOINT → main) always
		// engages the validator against config/required-env.yaml.
		SpringApplication app = new SpringApplication(PixelsRoverApplication.class);
		app.addListeners(new RequiredEnvValidator());
		app.run(args);
	}
}
