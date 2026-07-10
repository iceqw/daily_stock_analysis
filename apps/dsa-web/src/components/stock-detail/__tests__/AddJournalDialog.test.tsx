import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AddJournalDialog } from '../AddJournalDialog';

describe('AddJournalDialog', () => {
  it('validates empty submission', async () => {
    const onSubmit = vi.fn();

    render(
      <UiLanguageProvider>
        <AddJournalDialog
          isOpen
          stockCode="600519"
          market="cn"
          language="zh"
          onClose={vi.fn()}
          onSubmit={onSubmit}
        />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '保存日志' }));
    expect(await screen.findByText('请输入投资日志内容。')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits raw content', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <UiLanguageProvider>
        <AddJournalDialog
          isOpen
          stockCode="600519"
          market="cn"
          language="zh"
          onClose={vi.fn()}
          onSubmit={onSubmit}
        />
      </UiLanguageProvider>,
    );

    fireEvent.change(screen.getByLabelText('原文'), {
      target: { value: '记录新的研究观察' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存日志' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('记录新的研究观察');
    });
  });
});
