"""
CLI entrypoint for VoiceRide.

Phase 1: Manual trigger via command-line arguments.
Phase 2+: Voice-activated mode added.

Usage:
    python -m voiceride.cli book --pickup "Mekhri Circle" --drop "BMSIT College"
    python -m voiceride.cli status                    # Show recent runs
    python -m voiceride.cli status --run-id abc123    # Show events for a specific run
"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

console = Console()
app = typer.Typer(
    name="voiceride",
    help="🚗 VoiceRide — Personal voice assistant for parallel cab booking",
    add_completion=False,
)


@app.command()
def book(
    pickup: str = typer.Option(..., "--pickup", "-p", help="Pickup location"),
    drop: str = typer.Option(..., "--drop", "-d", help="Drop-off location"),
    ride_type: Optional[str] = typer.Option(None, "--type", "-t", help="Ride type: auto, mini, sedan"),
    platform: str = typer.Option("uber", "--platform", help="Platform to use (Phase 1: uber only)"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode"),
):
    """
    Book a ride on the specified platform.

    Example:
        python -m voiceride.cli book --pickup "Mekhri Circle" --drop "BMSIT College"
    """
    asyncio.run(_book_async(pickup, drop, ride_type, platform, headless))


async def _book_async(
    pickup: str, drop: str, ride_type: str | None, platform: str, headless: bool
) -> None:
    """Async implementation of the book command."""
    from voiceride.config import settings
    from voiceride.logging_config import setup_logging
    from voiceride.orchestrator.models import RideRequest, BookingState, PlatformName
    from voiceride.orchestrator.dispatcher import ParallelDispatcher
    from voiceride.orchestrator.first_confirm import FirstConfirmDetector
    from voiceride.platforms.uber.adapter import UberAdapter
    from voiceride.storage.database import Database
    from voiceride.notifications.desktop import (
        notify_driver_found,
        notify_cancel_failed,
        notify_no_drivers,
    )

    setup_logging()

    # Override headless setting if passed via CLI
    if headless:
        settings.uber_headless = True

    console.print(Panel(
        f"[bold green]🚗 VoiceRide — Booking Ride[/bold green]\n\n"
        f"  📍 Pickup:  [cyan]{pickup}[/cyan]\n"
        f"  🎯 Drop:    [cyan]{drop}[/cyan]\n"
        f"  🚕 Type:    [cyan]{ride_type or 'auto-select'}[/cyan]\n"
        f"  📱 Platform: [cyan]{platform}[/cyan]",
        title="Ride Request",
        border_style="green",
    ))

    # Initialize database
    db = Database()
    await db.connect()

    # Check for orphaned active runs from previous crashes
    active_runs = await db.get_active_runs()
    if active_runs:
        console.print(f"\n[yellow]⚠️  Found {len(active_runs)} active run(s) from previous sessions:[/yellow]")
        for run in active_runs:
            console.print(f"    Run {run.id}: {run.pickup} → {run.drop} (state: {run.state.value})")
        console.print("[yellow]   Please check these manually before proceeding.[/yellow]\n")

    # Create ride request
    request = RideRequest(pickup=pickup, drop=drop, ride_type=ride_type)

    # Initialize platform adapter
    adapter: UberAdapter | None = None
    try:
        if platform == "uber":
            adapter = UberAdapter()
        else:
            console.print(f"[red]❌ Platform '{platform}' not yet supported. Only 'uber' is available in Phase 1.[/red]")
            return

        console.print("\n[dim]Initializing Uber adapter (launching browser)...[/dim]")
        await adapter.initialize()
        console.print("[green]✅ Uber adapter initialized, session valid.[/green]\n")

        # Dispatch the booking
        dispatcher = ParallelDispatcher([adapter], db)
        console.print("[dim]Requesting quote and placing booking...[/dim]")
        run_id, platform_tasks = await dispatcher.dispatch(request)

        for task in platform_tasks:
            if task.success:
                console.print(
                    f"[green]✅ {task.platform.value.title()}: "
                    f"Booked! Fare: {task.quote.estimated_fare if task.quote else 'N/A'}[/green]"
                )
            else:
                console.print(f"[red]❌ {task.platform.value.title()}: {task.error}[/red]")

        # Check if any platform booked successfully
        booked_adapters = [adapter for t in platform_tasks if t.success]
        if not booked_adapters:
            console.print("\n[red]❌ Failed to book on all platforms. Aborting.[/red]")
            return

        # Poll for driver
        console.print(f"\n[dim]Polling for driver (every {settings.poll_interval_seconds}s, max {settings.max_poll_count} polls)...[/dim]\n")

        detector = FirstConfirmDetector([adapter], db, run_id)
        winner_status = await detector.run()

        if winner_status and winner_status.state == BookingState.DRIVER_CONFIRMED:
            # 🎉 Success!
            eta_str = f"{winner_status.driver_eta_seconds // 60} min" if winner_status.driver_eta_seconds else "unknown"
            console.print(Panel(
                f"[bold green]🎉 Driver Found![/bold green]\n\n"
                f"  📱 Platform: [cyan]{winner_status.platform.value.title()}[/cyan]\n"
                f"  👤 Driver:   [cyan]{winner_status.driver_name or 'N/A'}[/cyan]\n"
                f"  ⏱️  ETA:      [cyan]{eta_str}[/cyan]\n"
                f"  🚗 Vehicle:  [cyan]{winner_status.vehicle_info or 'N/A'}[/cyan]",
                title="✅ Ride Confirmed",
                border_style="green",
            ))

            # Desktop notification
            notify_driver_found(
                winner_status.platform.value,
                winner_status.driver_name,
                winner_status.driver_eta_seconds,
            )

            # Report cancel results
            for plat, cancel_result in detector.cancel_results.items():
                if cancel_result.success:
                    console.print(f"  [dim]✓ {plat.value.title()} cancelled successfully[/dim]")
                else:
                    console.print(f"  [red]⚠️ {plat.value.title()} cancel FAILED: {cancel_result.reason}[/red]")
                    notify_cancel_failed(plat.value, cancel_result.reason)

        else:
            # No driver found
            console.print(Panel(
                "[bold red]❌ No drivers found on any platform.[/bold red]\n\n"
                "  All platforms timed out or had no available drivers.\n"
                "  Try again in a few minutes.",
                title="No Drivers",
                border_style="red",
            ))
            notify_no_drivers()

        # Show run summary
        console.print(f"\n[dim]Run ID: {run_id} — view events with: voiceride status --run-id {run_id}[/dim]")

    except RuntimeError as e:
        console.print(f"\n[red]❌ Error: {e}[/red]")
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Unexpected error: {e}[/red]")
        import traceback
        traceback.print_exc()
    finally:
        # Always clean up
        if adapter:
            await adapter.teardown()
        await db.close()


@app.command()
def status(
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Show events for a specific run"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent runs to show"),
):
    """Show recent booking runs or events for a specific run."""
    asyncio.run(_status_async(run_id, limit))


async def _status_async(run_id: str | None, limit: int) -> None:
    """Async implementation of the status command."""
    from voiceride.logging_config import setup_logging
    from voiceride.storage.database import Database

    setup_logging()

    db = Database()
    await db.connect()

    try:
        if run_id:
            # Show events for a specific run
            run = await db.get_booking_run(run_id)
            if not run:
                console.print(f"[red]Run {run_id} not found.[/red]")
                return

            console.print(Panel(
                f"  ID:       {run.id}\n"
                f"  Pickup:   {run.pickup}\n"
                f"  Drop:     {run.drop}\n"
                f"  State:    {run.state.value}\n"
                f"  Winner:   {run.winning_platform.value if run.winning_platform else 'N/A'}\n"
                f"  Created:  {run.created_at}\n"
                f"  Completed: {run.completed_at or 'in progress'}",
                title=f"Booking Run {run_id}",
            ))

            events = await db.get_run_events(run_id)
            if events:
                table = Table(title="Event Log")
                table.add_column("Time", style="dim")
                table.add_column("Platform", style="cyan")
                table.add_column("Event", style="green")
                table.add_column("Detail")

                for event in events:
                    import json
                    table.add_row(
                        str(event.created_at)[11:19],  # HH:MM:SS
                        event.platform.value if event.platform else "system",
                        event.event_type.value,
                        json.dumps(event.detail) if event.detail else "",
                    )
                console.print(table)
        else:
            # Show recent runs
            runs = await db.get_recent_runs(limit)
            if not runs:
                console.print("[dim]No booking runs found.[/dim]")
                return

            table = Table(title=f"Recent Booking Runs (last {limit})")
            table.add_column("ID", style="dim")
            table.add_column("Pickup", style="cyan")
            table.add_column("Drop", style="cyan")
            table.add_column("State", style="green")
            table.add_column("Winner")
            table.add_column("Created")

            for run in runs:
                state_color = {
                    "driver_confirmed": "green",
                    "no_driver": "red",
                    "error": "red",
                    "cancelled": "yellow",
                    "polling": "blue",
                }.get(run.state.value, "white")

                table.add_row(
                    run.id[:8],
                    run.pickup[:25],
                    run.drop[:25],
                    f"[{state_color}]{run.state.value}[/{state_color}]",
                    run.winning_platform.value if run.winning_platform else "-",
                    str(run.created_at)[:19],
                )
            console.print(table)

    finally:
        await db.close()


@app.command()
def voice(
    platform: str = typer.Option("uber", "--platform", help="Platform to use (Phase 1: uber only)"),
    headless: bool = typer.Option(False, "--headless", help="Run browser in headless mode"),
    once: bool = typer.Option(False, "--once", help="Listen for a single command then exit"),
):
    """
    🎤 Voice-activated mode — speak your booking request naturally.

    Say something like "Book a cab from Mekhri Circle to BMSIT College"
    and VoiceRide will handle the rest.

    Example:
        python -m voiceride.cli voice
        python -m voiceride.cli voice --once   # Single command mode
    """
    # Check voice dependencies before entering async
    try:
        import speech_recognition  # noqa: F401
        import pyttsx3  # noqa: F401
        import openai  # noqa: F401
    except ImportError as e:
        console.print(
            f"[red]❌ Missing voice dependency: {e.name}[/red]\n\n"
            "[yellow]Install voice dependencies with:[/yellow]\n"
            "  pip install voiceride[voice]\n"
        )
        raise typer.Exit(1)

    asyncio.run(_voice_async(platform, headless, once))


async def _voice_async(platform: str, headless: bool, once: bool) -> None:
    """Async implementation of the voice command."""
    from voiceride.config import settings
    from voiceride.logging_config import setup_logging
    from voiceride.orchestrator.models import RideRequest, BookingState
    from voiceride.orchestrator.dispatcher import ParallelDispatcher
    from voiceride.orchestrator.first_confirm import FirstConfirmDetector
    from voiceride.platforms.uber.adapter import UberAdapter
    from voiceride.storage.database import Database
    from voiceride.notifications.desktop import (
        notify_driver_found,
        notify_cancel_failed,
        notify_no_drivers,
    )
    from voiceride.voice.listener import VoiceListener
    from voiceride.voice.stt import transcribe_audio
    from voiceride.voice.tts import (
        configure_voice,
        speak_listening,
        speak_processing,
        speak_booking_start,
        speak_driver_found,
        speak_no_drivers,
        speak_cancel_failed,
        speak_error,
        speak_not_understood,
        speak_goodbye,
    )
    from voiceride.nlu.intent import IntentExtractor

    setup_logging()

    # Override headless setting if passed via CLI
    if headless:
        settings.uber_headless = True

    # Configure TTS
    if settings.tts_enabled:
        configure_voice(rate=settings.tts_rate, volume=settings.tts_volume)

    console.print(Panel(
        "[bold cyan]🎤 VoiceRide — Voice Mode[/bold cyan]\n\n"
        "  Speak naturally to book a ride.\n"
        '  Example: "Book a cab from Mekhri Circle to BMSIT College"\n\n'
        "  [dim]Press Ctrl+C to exit.[/dim]",
        title="Voice Activated",
        border_style="cyan",
    ))

    # Initialize components
    listener = VoiceListener(pause_threshold=settings.silence_timeout)
    nlu = IntentExtractor()
    db = Database()
    await db.connect()

    adapter: UberAdapter | None = None
    loop_count = 0

    try:
        while True:
            loop_count += 1

            # ── Step 1: Listen ────────────────────────────────────
            console.print(f"\n[cyan]🎤 Listening... (say your booking request)[/cyan]")
            if settings.tts_enabled and loop_count == 1:
                speak_listening()

            audio = listener.listen_once(
                on_speech_start=lambda: console.print("[dim]  ▶ Speech detected...[/dim]"),
                on_speech_end=lambda: console.print("[dim]  ■ Recording complete.[/dim]"),
            )

            if audio is None:
                console.print("[yellow]No speech captured. Try again.[/yellow]")
                continue

            # ── Step 2: Transcribe ────────────────────────────────
            console.print("[dim]  🔄 Transcribing with Whisper...[/dim]")
            transcript = transcribe_audio(audio)

            if not transcript.strip():
                console.print("[yellow]  Couldn't transcribe any speech. Try again.[/yellow]")
                continue

            console.print(f'  📝 You said: [bold]"{transcript}"[/bold]')

            # ── Step 3: Extract Intent ────────────────────────────
            console.print("[dim]  🧠 Understanding your request...[/dim]")
            intent = await nlu.extract(transcript)

            if not intent.is_booking:
                console.print(f"[yellow]  ⚠️ Not a booking request: {intent.reason}[/yellow]")
                if settings.tts_enabled:
                    speak_not_understood()
                if once:
                    break
                continue

            pickup = intent.pickup or "Current Location"
            drop = intent.drop
            ride_type = intent.ride_type

            console.print(Panel(
                f"[bold green]🚗 Booking Request Understood[/bold green]\n\n"
                f"  📍 Pickup:  [cyan]{pickup}[/cyan]\n"
                f"  🎯 Drop:    [cyan]{drop}[/cyan]\n"
                f"  🚕 Type:    [cyan]{ride_type or 'auto-select'}[/cyan]",
                border_style="green",
            ))

            if settings.tts_enabled:
                speak_processing()
                speak_booking_start(pickup, drop, ride_type)

            # ── Step 4: Book the Ride (reuse Phase 1 pipeline) ────
            request = RideRequest(pickup=pickup, drop=drop, ride_type=ride_type)

            try:
                if adapter is None:
                    if platform == "uber":
                        adapter = UberAdapter()
                    else:
                        console.print(f"[red]❌ Platform '{platform}' not yet supported.[/red]")
                        if settings.tts_enabled:
                            speak_error(f"Platform {platform} is not yet supported.")
                        break

                    console.print("\n[dim]Initializing Uber adapter (launching browser)...[/dim]")
                    await adapter.initialize()
                    console.print("[green]✅ Uber adapter initialized.[/green]\n")

                # Dispatch
                dispatcher = ParallelDispatcher([adapter], db)
                console.print("[dim]Requesting quote and placing booking...[/dim]")
                run_id, platform_tasks = await dispatcher.dispatch(request)

                for task in platform_tasks:
                    if task.success:
                        console.print(
                            f"[green]✅ {task.platform.value.title()}: "
                            f"Booked! Fare: {task.quote.estimated_fare if task.quote else 'N/A'}[/green]"
                        )
                    else:
                        console.print(f"[red]❌ {task.platform.value.title()}: {task.error}[/red]")

                booked = [t for t in platform_tasks if t.success]
                if not booked:
                    console.print("\n[red]❌ Failed to book on all platforms.[/red]")
                    if settings.tts_enabled:
                        speak_error("Failed to book on all platforms.")
                    if once:
                        break
                    continue

                # Poll for driver
                console.print(f"\n[dim]Polling for driver...[/dim]\n")
                detector = FirstConfirmDetector([adapter], db, run_id)
                winner_status = await detector.run()

                if winner_status and winner_status.state == BookingState.DRIVER_CONFIRMED:
                    eta_str = f"{winner_status.driver_eta_seconds // 60} min" if winner_status.driver_eta_seconds else "unknown"
                    console.print(Panel(
                        f"[bold green]🎉 Driver Found![/bold green]\n\n"
                        f"  📱 Platform: [cyan]{winner_status.platform.value.title()}[/cyan]\n"
                        f"  👤 Driver:   [cyan]{winner_status.driver_name or 'N/A'}[/cyan]\n"
                        f"  ⏱️  ETA:      [cyan]{eta_str}[/cyan]\n"
                        f"  🚗 Vehicle:  [cyan]{winner_status.vehicle_info or 'N/A'}[/cyan]",
                        title="✅ Ride Confirmed",
                        border_style="green",
                    ))

                    # TTS + desktop notification
                    if settings.tts_enabled:
                        speak_driver_found(
                            winner_status.platform.value,
                            winner_status.driver_name,
                            winner_status.driver_eta_seconds,
                        )
                    notify_driver_found(
                        winner_status.platform.value,
                        winner_status.driver_name,
                        winner_status.driver_eta_seconds,
                    )

                    # Report cancel results
                    for plat, cancel_result in detector.cancel_results.items():
                        if cancel_result.success:
                            console.print(f"  [dim]✓ {plat.value.title()} cancelled[/dim]")
                        else:
                            console.print(f"  [red]⚠️ {plat.value.title()} cancel FAILED: {cancel_result.reason}[/red]")
                            if settings.tts_enabled:
                                speak_cancel_failed(plat.value)
                            notify_cancel_failed(plat.value, cancel_result.reason)

                else:
                    console.print(Panel(
                        "[bold red]❌ No drivers found.[/bold red]\n\n"
                        "  Try again in a few minutes.",
                        title="No Drivers",
                        border_style="red",
                    ))
                    if settings.tts_enabled:
                        speak_no_drivers()
                    notify_no_drivers()

                console.print(f"\n[dim]Run ID: {run_id}[/dim]")

            except RuntimeError as e:
                console.print(f"\n[red]❌ Error: {e}[/red]")
                if settings.tts_enabled:
                    speak_error(str(e))
            except Exception as e:
                console.print(f"\n[red]❌ Unexpected error: {e}[/red]")
                if settings.tts_enabled:
                    speak_error("An unexpected error occurred.")
                import traceback
                traceback.print_exc()

            if once:
                break

            # Reset adapter for next booking (close and re-init)
            if adapter:
                await adapter.teardown()
                adapter = None

    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Exiting voice mode.[/yellow]")
        if settings.tts_enabled:
            speak_goodbye()
    finally:
        if adapter:
            await adapter.teardown()
        await db.close()


if __name__ == "__main__":
    app()
