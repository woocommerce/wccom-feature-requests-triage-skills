# Shared Display & Pagination Conventions

These rules apply to every skill whenever a list of feature requests is
displayed for review and selection.

See also: `RULES.md` (ID display, URL carry-through, HTML entities,
translation, plain-text comments, confidence labels).

---

## Pagination — when to paginate

Applies to **flat lists** of FRs (completed matches, spam, support).

If the list has **20 or fewer items**: show them all at once.

If the list has **more than 20 items**: page in batches of 20, using the
format below.

### Grouped phases

The duplicates and stale phases display FRs nested under groups. Pagination
behaviour differs:

- **Duplicates** — group items sequentially across all groups (item 21 on
  page 2 is `[21].`). Pagination breaks at item boundaries, not group
  boundaries. A group may span pages. Group headers reprint on each page.
- **Stale** — paginate **within a single group** if that group has >20 FRs.
  Groups themselves are navigated via the letter menu in the stale skill,
  not paginated.

---

## Page format

```
Showing items [A]–[B] of [total] · Page [X] of [Y]

[A]. ID [id] — "[title]"
     … (all fields for this item as defined by the skill)

[A+1]. …
…
[B]. …

─────────────────────────────────────
Select items from this page by number, then choose:
  [N] Next page    [P] Prev page    [D] Done selecting    [S] Skip all
Running total selected: [count] item(s)
─────────────────────────────────────
```

- Items are numbered **sequentially across all pages** (item 21 on page 2 is
  `[21].`, not `[1].`), so numbers remain stable and unambiguous when
  the user references them.
- The user may select any numbers from the current page, then navigate to
  another page and select more. Selections accumulate across pages.
- Show a **running total** of how many items are selected so far at the bottom
  of every page.
- Already-selected items from previous pages are shown with a `✔` prefix when
  they reappear (e.g. if navigating backwards).

---

## Navigation commands

| Input | Action |
|---|---|
| One or more numbers (e.g. `1 3 5`) | Toggle selection for those items on the current page |
| `N` or `next` | Advance to the next page |
| `P` or `prev` | Go back to the previous page |
| `A` or `all` | Select all items across all pages |
| `D` or `done` | Finish selecting; proceed to the confirmation step |
| `S` or `skip` | Select nothing; skip this phase |

---

## After selection

Once the user types `done` (or after the last page if they haven't navigated
away), display the full selection for confirmation before taking any action:

```
You've selected [N] item(s):

  • ID [id] — "[title]"
  • ID [id] — "[title]"
  …

Proceed? (Y / N)
```

Then continue with the skill's normal confirmation → preview → execute flow.
