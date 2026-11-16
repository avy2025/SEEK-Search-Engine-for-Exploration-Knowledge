import type { SearchHistoryEntry } from './api';

export interface SearchHistoryGroup {
  label: string;
  entries: SearchHistoryEntry[];
}

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function calendarDay(dateKey: string): number {
  const [year, month, day] = dateKey.split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

export function groupSearchHistory(
  entries: SearchHistoryEntry[],
  now: Date = new Date(),
): SearchHistoryGroup[] {
  const todayKey = localDateKey(now);
  const today = calendarDay(todayKey);
  const groups = new Map<string, SearchHistoryEntry[]>();
  const sortedEntries = [...entries].sort((a, b) => {
    const timeDifference = Date.parse(b.created_at) - Date.parse(a.created_at);
    return timeDifference || b.id.localeCompare(a.id);
  });

  for (const entry of sortedEntries) {
    const date = new Date(entry.created_at);
    const dateKey = localDateKey(date);
    const ageInDays = (today - calendarDay(dateKey)) / 86_400_000;
    const label = ageInDays === 0
      ? 'Today'
      : ageInDays === 1
        ? 'Yesterday'
        : ageInDays <= 7
          ? 'Previous 7 Days'
          : date.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          });
    const groupEntries = groups.get(label) ?? [];
    groupEntries.push(entry);
    groups.set(label, groupEntries);
  }

  return Array.from(groups, ([label, groupedEntries]) => ({
    label,
    entries: groupedEntries,
  }));
}
