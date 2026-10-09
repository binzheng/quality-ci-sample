import { useState, type FormEvent } from 'react';
import { truncate } from '../utils/format';
import { Button } from './Button';

export interface TodoItem {
  id: number;
  title: string;
  done: boolean;
}

export interface TodoListProps {
  /** 初期表示する TODO */
  initialItems?: TodoItem[];
  /** タイトルの最大表示文字数 */
  maxTitleLength?: number;
}

export function TodoList({ initialItems = [], maxTitleLength = 40 }: TodoListProps) {
  const [items, setItems] = useState<TodoItem[]>(initialItems);
  const [title, setTitle] = useState('');

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) {
      return;
    }
    const nextId = items.reduce((max, item) => Math.max(max, item.id), 0) + 1;
    setItems([...items, { id: nextId, title: trimmed, done: false }]);
    setTitle('');
  };

  const toggle = (id: number) =>
    setItems(items.map((item) => (item.id === id ? { ...item, done: !item.done } : item)));

  const remove = (id: number) => setItems(items.filter((item) => item.id !== id));

  const remaining = items.filter((item) => !item.done).length;

  return (
    <section className="todo">
      <form className="todo__form" onSubmit={handleSubmit}>
        <input
          aria-label="新しいTODO"
          placeholder="やることを入力"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <Button type="submit" label="追加" />
      </form>
      {items.length === 0 ? (
        <p className="todo__empty">TODO はありません</p>
      ) : (
        <ul className="todo__list">
          {items.map((item) => (
            <li key={item.id} className={item.done ? 'todo__item todo__item--done' : 'todo__item'}>
              <label>
                <input type="checkbox" checked={item.done} onChange={() => toggle(item.id)} />{' '}
                <span title={item.title}>{truncate(item.title, maxTitleLength)}</span>
              </label>
              <Button
                variant="danger"
                label="削除"
                aria-label={`${item.title} を削除`}
                onClick={() => remove(item.id)}
              />
            </li>
          ))}
        </ul>
      )}
      <p className="todo__summary">{`残り ${remaining} 件`}</p>
    </section>
  );
}
