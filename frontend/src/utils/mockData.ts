export const ARABICA_BASE = 223.40;
export const ROBUSTA_BASE = 4105;

export const genPriceSeries = (base: number, days: number, volatility = 0.015) => {
  const data = [];
  let price = base;
  const now = new Date();
  for (let i = -days; i <= 7; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    price += price * (Math.random() - 0.48) * volatility;
    const isForecast = i > 0;
    data.push({
      date: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      price: parseFloat(price.toFixed(2)),
      forecast: isForecast ? parseFloat(price.toFixed(2)) : null,
      upper: isForecast ? parseFloat((price * 1.035).toFixed(2)) : null,
      lower: isForecast ? parseFloat((price * 0.965).toFixed(2)) : null,
      type: isForecast ? "forecast" : "historical",
    });
  }
  return data;
};

export const MARKET_DATA_FALLBACK = {
  arabica: { symbol: "KC1", name: "Arabica Futures", price: ARABICA_BASE, change: 3.2, changePct: 1.45, currency: "USc/lb", volume: "28,412", open: 219.90, high: 224.85, low: 218.60 },
  robusta: { symbol: "RC1", name: "Robusta Futures", price: ROBUSTA_BASE, change: -35, changePct: -0.84, currency: "$/MT", volume: "14,270", open: 4140, high: 4155, low: 4085 },
};
