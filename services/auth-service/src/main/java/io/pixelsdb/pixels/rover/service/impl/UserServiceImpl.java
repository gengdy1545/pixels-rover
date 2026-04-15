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
package io.pixelsdb.pixels.rover.service.impl;

import io.pixelsdb.pixels.rover.constant.HttpStatus;
import io.pixelsdb.pixels.rover.constant.ErrorCode;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.mapper.UserRepository;
import io.pixelsdb.pixels.rover.model.User;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import io.pixelsdb.pixels.rover.rest.response.UserInfoResponse;
import io.pixelsdb.pixels.rover.service.UserService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;

@Service
public class UserServiceImpl implements UserService
{
    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    public UserServiceImpl(UserRepository userRepository, PasswordEncoder passwordEncoder)
    {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    public void register(RegisterRequest request)
    {
        User existUser = userRepository.findByEmail(request.getEmail());
        if (existUser != null)
        {
            throw new ServiceException("User already exists", ErrorCode.RESOURCE_CONFLICT);
        }

        User user = new User();
        user.setName(request.getName());
        user.setEmail(request.getEmail());
        user.setAffiliation(request.getAffiliation());
        user.setPassword(passwordEncoder.encode(request.getPassword()));
        user.setCreateTime(new Timestamp(System.currentTimeMillis()));
        userRepository.save(user);
    }

    @Override
    public UserInfoResponse getUserInfo(String email)
    {
        User user = userRepository.findByEmail(email);
        if (user == null)
        {
            throw new ServiceException("User not found", ErrorCode.RESOURCE_NOT_FOUND);
        }

        return new UserInfoResponse(user.getId(), user.getName(), user.getEmail(), user.getAffiliation());
    }
}
