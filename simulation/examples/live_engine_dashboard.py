"""Run the graphical live Mini-FADEC engine dashboard."""

from simulation.application.live_dashboard import LiveEngineDashboard


def main() -> None:
    """Create and run the live engine dashboard."""

    LiveEngineDashboard().run()


if __name__ == "__main__":
    main()
