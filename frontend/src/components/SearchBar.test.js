import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import SearchBar from './SearchBar';
import { resolveSymbols, searchInstruments } from '../api';

jest.mock('../api', () => ({
  resolveSymbols: jest.fn(),
  searchInstruments: jest.fn(),
}));

beforeEach(() => {
  searchInstruments.mockResolvedValue([]);
  resolveSymbols.mockResolvedValue([
    { query: 'HDFC Bank Limited', symbol: 'HDFCBANK', exchange: 'NSE' },
  ]);
});

test('resolves a company name before opening stock research on Enter', async () => {
  const onSelect = jest.fn();
  render(<SearchBar onSelect={onSelect} />);
  const input = screen.getByPlaceholderText(/Search stock by name or symbol/i);

  fireEvent.change(input, { target: { value: 'HDFC Bank Limited' } });
  fireEvent.keyDown(input, { key: 'Enter' });

  await waitFor(() => expect(resolveSymbols).toHaveBeenCalledWith(['HDFC Bank Limited']));
  expect(onSelect).toHaveBeenCalledWith('HDFCBANK', 'NSE');
});

