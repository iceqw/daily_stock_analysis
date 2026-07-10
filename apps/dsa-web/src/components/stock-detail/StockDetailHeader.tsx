import type React from 'react';
import { Badge } from '../common';
import type { UiLanguage } from '../../i18n/uiText';
import { formatMarketLabel, getStockDetailText } from './utils';

interface StockDetailHeaderProps {
  stockCode: string;
  market: string;
  stockName?: string | null;
  language: UiLanguage;
}

export const StockDetailHeader: React.FC<StockDetailHeaderProps> = ({
  stockCode,
  market,
  stockName,
  language,
}) => {
  const text = getStockDetailText(language);
  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-border/70 bg-card/80 p-6 shadow-soft-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <span className="label-uppercase">{text.archiveTitle}</span>
          <div>
            <h1 className="text-3xl font-semibold text-foreground">{stockCode}</h1>
            {stockName ? <p className="mt-2 text-sm text-secondary-text">{stockName}</p> : null}
          </div>
          <p className="max-w-3xl text-sm text-secondary-text">{text.archiveSubtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="info" size="md">{formatMarketLabel(market, language)}</Badge>
          <Badge variant="history" size="md">{stockCode}</Badge>
        </div>
      </div>
    </div>
  );
};
