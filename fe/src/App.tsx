import { TodoList } from './components/TodoList';
import { formatPrice } from './utils/format';

const SAMPLE_PRICE = 1980;

export default function App() {
  return (
    <main className="app">
      <h1>Demo FE</h1>
      <p>本日のおすすめ: {formatPrice(SAMPLE_PRICE)}</p>
      <TodoList
        initialItems={[
          { id: 1, title: 'CI のレポートを確認する', done: true },
          { id: 2, title: 'PR をレビューする', done: false },
        ]}
      />
    </main>
  );
}
