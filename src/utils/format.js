const trimZeros = (value) => {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric.toString() : '0';
};

export const formatCurrency = (value) => {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  let formatted;

  if (absValue >= 1000) {
    const compact = absValue / 1000;
    const decimals = compact >= 10 ? 0 : 2;
    formatted = `$${trimZeros(compact.toFixed(decimals))}K`;
  } else if (absValue >= 100) {
    formatted = `$${trimZeros(absValue.toFixed(0))}`;
  } else if (absValue === 0) {
    formatted = '$0';
  } else {
    formatted = `$${trimZeros(absValue.toFixed(1))}`;
  }

  return sign ? `${sign}${formatted}` : formatted;
};

export const formatPercent = (value) => {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  const absValue = Math.abs(value);
  const formatted = trimZeros(absValue.toFixed(1));
  return `${sign}${formatted}%`;
};

export const pluralize = (word, count) => (count === 1 ? word : `${word}s`);

export const sentimentClass = (value) => {
  if (value > 0) {
    return 'positive';
  }

  if (value < 0) {
    return 'negative';
  }

  return 'neutral';
};
