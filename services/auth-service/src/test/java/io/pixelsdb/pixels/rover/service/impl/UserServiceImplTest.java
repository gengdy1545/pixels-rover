package io.pixelsdb.pixels.rover.service.impl;

import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.mapper.UserRepository;
import io.pixelsdb.pixels.rover.model.User;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import io.pixelsdb.pixels.rover.rest.response.UserInfoResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class UserServiceImplTest
{
    @Mock
    private UserRepository userRepository;

    @Mock
    private PasswordEncoder passwordEncoder;

    @InjectMocks
    private UserServiceImpl userService;

    @Test
    void registerShouldCreateUserWhenEmailNotExists()
    {
        RegisterRequest request = new RegisterRequest();
        request.setName("Alice");
        request.setEmail("alice@example.com");
        request.setAffiliation("Pixels");
        request.setPassword("secret");

        when(userRepository.findByEmail("alice@example.com")).thenReturn(null);
        when(passwordEncoder.encode("secret")).thenReturn("encoded-secret");

        userService.register(request);

        ArgumentCaptor<User> userCaptor = ArgumentCaptor.forClass(User.class);
        verify(userRepository).save(userCaptor.capture());
        User savedUser = userCaptor.getValue();
        assertEquals("Alice", savedUser.getName());
        assertEquals("alice@example.com", savedUser.getEmail());
        assertEquals("Pixels", savedUser.getAffiliation());
        assertEquals("encoded-secret", savedUser.getPassword());
        assertNotNull(savedUser.getCreateTime());
    }

    @Test
    void registerShouldThrowWhenEmailAlreadyExists()
    {
        RegisterRequest request = new RegisterRequest();
        request.setEmail("alice@example.com");

        when(userRepository.findByEmail("alice@example.com")).thenReturn(new User());

        ServiceException exception = assertThrows(ServiceException.class, () -> userService.register(request));
        assertEquals("User already exists", exception.getMessage());
    }

    @Test
    void getUserInfoShouldReturnSafeFields()
    {
        User user = new User();
        user.setId(1L);
        user.setName("Alice");
        user.setEmail("alice@example.com");
        user.setAffiliation("Pixels");
        user.setPassword("encoded-secret");

        when(userRepository.findByEmail("alice@example.com")).thenReturn(user);

        UserInfoResponse userInfo = userService.getUserInfo("alice@example.com");

        assertEquals(1L, userInfo.getId());
        assertEquals("Alice", userInfo.getName());
        assertEquals("alice@example.com", userInfo.getEmail());
        assertEquals("Pixels", userInfo.getAffiliation());
    }
}
