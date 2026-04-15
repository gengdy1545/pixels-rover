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
package io.pixelsdb.pixels.rover.rest.request;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;

/**
 * Register request DTO.
 *
 * @author pixels
 */
public class RegisterRequest
{
    @NotBlank(message = "Name cannot be blank")
    private String name;

    @Email(message = "Email format is invalid")
    @NotBlank(message = "Email cannot be blank")
    private String email;

    @NotBlank(message = "Affiliation cannot be blank")
    private String affiliation;

    @NotBlank(message = "Password cannot be blank")
    private String password;

    private String captcha;
    private String captchaKey;

    public String getName()
    {
        return name;
    }

    public void setName(String name)
    {
        this.name = name;
    }

    public String getEmail()
    {
        return email;
    }

    public void setEmail(String email)
    {
        this.email = email;
    }

    public String getAffiliation()
    {
        return affiliation;
    }

    public void setAffiliation(String affiliation)
    {
        this.affiliation = affiliation;
    }

    public String getPassword()
    {
        return password;
    }

    public void setPassword(String password)
    {
        this.password = password;
    }

    public String getCaptcha()
    {
        return captcha;
    }

    public void setCaptcha(String captcha)
    {
        this.captcha = captcha;
    }

    public String getCaptchaKey()
    {
        return captchaKey;
    }

    public void setCaptchaKey(String captchaKey)
    {
        this.captchaKey = captchaKey;
    }
}
