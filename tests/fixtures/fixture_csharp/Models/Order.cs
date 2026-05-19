namespace App.Models
{
    public class Order
    {
        public string Id { get; set; }
        public string UserId { get; set; }
        public decimal Total { get; set; }

        public static decimal CalculateTotal(decimal[] items)
        {
            decimal sum = 0;
            foreach (var item in items) sum += item;
            return sum;
        }
    }
}
