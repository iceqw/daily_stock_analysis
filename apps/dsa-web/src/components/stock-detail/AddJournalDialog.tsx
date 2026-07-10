import type React from 'react';
import { useState } from 'react';
import { Button, Drawer, InlineAlert } from '../common';
import type { UiLanguage } from '../../i18n/uiText';
import { getStockDetailText } from './utils';

interface AddJournalDialogProps {
  isOpen: boolean;
  stockCode: string;
  market: string;
  language: UiLanguage;
  isSubmitting?: boolean;
  error?: string | null;
  onClose: () => void;
  onSubmit: (rawContent: string) => Promise<void> | void;
}

export const AddJournalDialog: React.FC<AddJournalDialogProps> = ({
  isOpen,
  stockCode,
  market,
  language,
  isSubmitting = false,
  error,
  onClose,
  onSubmit,
}) => {
  const text = getStockDetailText(language);
  const [rawContent, setRawContent] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = rawContent.trim();
    if (!trimmed) {
      setValidationError(text.inputRequired);
      return;
    }
    setValidationError(null);
    await onSubmit(trimmed);
  };

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={text.createJournal} width="max-w-2xl">
      <div className="space-y-5">
        <div className="rounded-2xl border border-border/60 bg-surface-2/70 p-4 text-sm text-secondary-text">
          <div>{stockCode}</div>
          <div className="mt-1">{text.market}: {market}</div>
        </div>

        {error ? <InlineAlert variant="danger" message={error} /> : null}
        {validationError ? <InlineAlert variant="warning" message={validationError} /> : null}

        <div className="space-y-2">
          <label htmlFor="journal-raw-content" className="text-sm font-medium text-foreground">
            {text.rawContent}
          </label>
          <textarea
            id="journal-raw-content"
            className="input-surface input-focus-glow min-h-[260px] w-full rounded-2xl border bg-transparent px-4 py-3 text-sm leading-7 text-foreground focus:outline-none"
            value={rawContent}
            onChange={(event) => setRawContent(event.target.value)}
            placeholder={text.journalPlaceholder}
          />
        </div>

        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>
            {language === 'zh' ? '取消' : 'Cancel'}
          </Button>
          <Button variant="primary" isLoading={isSubmitting} onClick={() => void handleSubmit()}>
            {text.saveJournal}
          </Button>
        </div>
      </div>
    </Drawer>
  );
};
