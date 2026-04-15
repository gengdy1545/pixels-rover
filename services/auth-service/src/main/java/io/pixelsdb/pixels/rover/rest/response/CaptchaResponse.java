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
package io.pixelsdb.pixels.rover.rest.response;

public class CaptchaResponse
{
    private String captchaKey;
    private String captchaImage;

    public CaptchaResponse()
    {
    }

    public CaptchaResponse(String captchaKey, String captchaImage)
    {
        this.captchaKey = captchaKey;
        this.captchaImage = captchaImage;
    }

    public String getCaptchaKey()
    {
        return captchaKey;
    }

    public void setCaptchaKey(String captchaKey)
    {
        this.captchaKey = captchaKey;
    }

    public String getCaptchaImage()
    {
        return captchaImage;
    }

    public void setCaptchaImage(String captchaImage)
    {
        this.captchaImage = captchaImage;
    }
}
