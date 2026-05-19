using App.Models;

namespace App.Services
{
    public class AuthService
    {
        public User Authenticate(string email, string password)
        {
            if (string.IsNullOrEmpty(email)) return null;
            return new User { Id = "1", Email = email, Name = "Auth User" };
        }

        public bool ValidateToken(string token)
        {
            return !string.IsNullOrEmpty(token) && token.Length > 10;
        }
    }
}
