using App.Models;

namespace App.Services
{
    public class OrderService
    {
        public Order PlaceOrder(decimal[] items)
        {
            var total = Order.CalculateTotal(items);
            return new Order { Id = "o1", UserId = "u1", Total = total };
        }
    }
}
