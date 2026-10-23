"""Demonstrate the real DST-safe issue-grid function without opening archives."""
from kden_v375.archive_readers import issue_time_grid


def main():
    for day, expected in (("2024-03-09", 57), ("2024-03-10", 53)):
        grid = issue_time_grid(day)
        assert len(grid) == expected
        print(f"{day}: {len(grid)} issue times, {grid[0].isoformat()} to {grid[-1].isoformat()}")
    print("Spring-forward omits the nonexistent 02:00 hour; no weather data was read.")
    print("HRRR cycles initialize hourly; 105 minutes is the availability delay, not update spacing.")


if __name__ == "__main__":
    main()
