import type { Meta, StoryObj } from '@storybook/react';
import { TodoList } from './TodoList';

const meta = {
  title: 'Components/TodoList',
  component: TodoList,
  tags: ['autodocs'],
} satisfies Meta<typeof TodoList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const WithItems: Story = {
  args: {
    initialItems: [
      { id: 1, title: 'CI のレポートを確認する', done: true },
      { id: 2, title: 'PR をレビューする', done: false },
      { id: 3, title: 'develop にマージする', done: false },
    ],
  },
};

export const LongTitle: Story = {
  args: {
    maxTitleLength: 12,
    initialItems: [{ id: 1, title: 'とても長いタイトルの TODO は省略記号付きで表示されます', done: false }],
  },
};
