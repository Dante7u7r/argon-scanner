package com.app.services;

import com.app.models.User;

public class AuthService {
    public User authenticate(String email, String password) {
        if (email == null || password == null) return null;
        return new User("1", email, "Auth User");
    }

    public boolean validateToken(String token) {
        return token != null && token.length() > 10;
    }
}
