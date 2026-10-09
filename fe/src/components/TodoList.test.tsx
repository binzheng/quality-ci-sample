import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TodoList } from './TodoList';

const items = [
  { id: 1, title: '牛乳を買う', done: false },
  { id: 2, title: '本を返す', done: true },
];

describe('TodoList', () => {
  it('shows an empty message when there are no items', () => {
    render(<TodoList />);
    expect(screen.getByText('TODO はありません')).toBeInTheDocument();
    expect(screen.getByText('残り 0 件')).toBeInTheDocument();
  });

  it('renders initial items and remaining count', () => {
    render(<TodoList initialItems={items} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('残り 1 件')).toBeInTheDocument();
  });

  it('adds a new item and clears the input', () => {
    render(<TodoList initialItems={items} />);
    const input = screen.getByLabelText('新しいTODO');
    fireEvent.change(input, { target: { value: '  掃除する  ' } });
    fireEvent.click(screen.getByRole('button', { name: '追加' }));
    expect(screen.getByText('掃除する')).toBeInTheDocument();
    expect(input).toHaveValue('');
    expect(screen.getByText('残り 2 件')).toBeInTheDocument();
  });

  it('ignores blank input', () => {
    render(<TodoList />);
    fireEvent.change(screen.getByLabelText('新しいTODO'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: '追加' }));
    expect(screen.getByText('TODO はありません')).toBeInTheDocument();
  });

  it('toggles and removes items', () => {
    render(<TodoList initialItems={items} />);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(screen.getByText('残り 0 件')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '牛乳を買う を削除' }));
    expect(screen.queryByText('牛乳を買う')).not.toBeInTheDocument();
  });

  it('truncates long titles', () => {
    render(<TodoList initialItems={[{ id: 1, title: 'abcdefghij', done: false }]} maxTitleLength={5} />);
    expect(screen.getByText('abcd…')).toHaveAttribute('title', 'abcdefghij');
  });
});
